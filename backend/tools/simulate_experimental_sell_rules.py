from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from math import floor
from pathlib import Path
from typing import Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scoring.technical import calculate_technical_score, moving_average
from services.backtest_service import BacktestService
from services.event_service import EventService
from services.macro_data_service import MacroDataService
from services.sp500_market_service import SP500MarketService


@dataclass
class SimulationContext:
    backtest_service: BacktestService


def _compute_max_drawdown(values: List[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak != 0 else 0
        if dd > max_dd:
            max_dd = dd
    return round(max_dd * 100, 2)


def _compute_trade_followup_metrics(trades: List[Dict], price_history: List[tuple[str, float]]) -> tuple[List[float], List[float]]:
    index_by_date = {dt: idx for idx, (dt, _) in enumerate(price_history)}
    sell_post_return_20d_pct: List[float] = []
    buyback_return_pct: List[float] = []
    for idx, trade in enumerate(trades):
        if trade["action"] != "SELL":
            continue
        sell_idx = index_by_date.get(trade["date"])
        if sell_idx is not None and sell_idx + 20 < len(price_history):
            post_price = price_history[sell_idx + 20][1]
            sell_post_return_20d_pct.append(round(((post_price / trade["price"]) - 1) * 100, 4))
        next_buy = next((t for t in trades[idx + 1 :] if t["action"] == "BUY"), None)
        if next_buy is not None:
            buyback_return_pct.append(round(((next_buy["price"] / trade["price"]) - 1) * 100, 4))
    return sell_post_return_20d_pct, buyback_return_pct


def _summarize_rule_result(rule_name: str, index_type: str, result: Dict) -> Dict:
    trades = result.get("trades", [])
    sells = [t for t in trades if t["action"] == "SELL"]
    buys = [t for t in trades if t["action"] == "BUY"]
    sell_dates = [t["date"] for t in sells]
    buy_dates = [t["date"] for t in buys]
    sell_reasons = sorted({str(t.get("reason")) for t in sells if t.get("reason")})
    buy_reasons = sorted({str(t.get("reason")) for t in buys if t.get("reason")})
    sell_post_return_20d_pct, buyback_return_pct = _compute_trade_followup_metrics(
        trades, result.get("price_history", [])
    )
    final_equity = float(result["final_value"])
    hold_equity = float(result["buy_and_hold_final"])
    diff_amount = final_equity - hold_equity
    diff_pct = ((diff_amount / hold_equity) * 100) if hold_equity != 0 else 0.0

    return {
        "rule_name": rule_name,
        "index_type": index_type,
        "final_equity": round(final_equity, 2),
        "hold_equity": round(hold_equity, 2),
        "diff_amount": round(diff_amount, 2),
        "diff_pct": round(diff_pct, 2),
        "trade_count": len(trades),
        "sell_count": len(sells),
        "buy_count": len(buys),
        "sell_dates": sell_dates,
        "buy_dates": buy_dates,
        "sell_reasons": sell_reasons,
        "buy_reasons": buy_reasons,
        "sell_post_return_20d_pct": sell_post_return_20d_pct,
        "buyback_return_pct": buyback_return_pct,
        "max_drawdown": result.get("max_drawdown_pct"),
    }


def _run_simulation_core(
    ctx: SimulationContext,
    *,
    index_type: str,
    rule_name: str,
    sell_threshold: float,
    technical_threshold: Optional[float],
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    score_ma: int,
) -> Dict:
    svc = ctx.backtest_service
    raw_history = svc.market_service.get_price_history_range(
        start_date, end_date, allow_fallback=svc.allow_fallback, index_type=index_type
    )
    price_history = svc._prepare_price_history(raw_history, index_type)
    macro_series = svc.macro_service.get_macro_series_range(start_date, end_date)

    first_price = price_history[0][1]
    initial_shares = floor(initial_cash / first_price)
    cash = initial_cash - (initial_shares * first_price)
    shares = initial_shares
    trades: List[Dict] = []
    sell_cooldown_days_remaining = 0
    days_since_last_sell: int | None = None
    recent_scores: List[float] = []
    portfolio_values: List[float] = []
    overheat_event_date: str | None = None
    overheat_event_consumed = False
    prev_overheat_state = False
    buy_reason_counts = {"initial_threshold": 0, "pattern_a": 0, "pattern_b": 0, "both": 0, "day60": 0}

    hold_cash = initial_cash
    first_price = price_history[0][1]
    hold_shares = floor(hold_cash / first_price)
    hold_cash -= hold_shares * first_price

    for idx, (date_str, close) in enumerate(price_history):
        if sell_cooldown_days_remaining > 0:
            sell_cooldown_days_remaining -= 1
        if days_since_last_sell is not None:
            days_since_last_sell += 1

        if idx >= max(score_ma - 1, 199):
            sub_history = price_history[: idx + 1]
            total_score = float(svc._calculate_scores(sub_history, macro_series, date.fromisoformat(date_str), score_ma))
            technical_score, _ = calculate_technical_score(sub_history, base_window=score_ma)
            recent_scores.append(total_score)
            closes = [p[1] for p in sub_history]
            ma20_series = moving_average(closes, 20)
            ma50_series = moving_average(closes, 50)
            cooldown_active = sell_cooldown_days_remaining > 0
            is_overheat_today = total_score >= sell_threshold
            if is_overheat_today and not prev_overheat_state:
                overheat_event_date = date_str
                overheat_event_consumed = False
            prev_overheat_state = is_overheat_today
            score_declining_3days = (
                len(recent_scores) >= 4
                and recent_scores[-1] < recent_scores[-2] < recent_scores[-3] < recent_scores[-4]
            )
            close_below_ma20 = close < ma20_series[-1]
            peakout_detected = score_declining_3days and close_below_ma20
            close_below_ma20_2days = (
                len(closes) >= 2
                and close < ma20_series[-1]
                and closes[-2] < ma20_series[-2]
            )
            close_below_ma50 = close < ma50_series[-1]
            confirmation_detected = close_below_ma20_2days or close_below_ma50
            overheat_event_active = overheat_event_date is not None and not overheat_event_consumed
            sell_gate_open = overheat_event_active and peakout_detected and confirmation_detected

            buy_reason = None
            if days_since_last_sell is None:
                buy_gate_open = total_score < buy_threshold
                if buy_gate_open:
                    buy_reason = "initial_threshold"
            elif days_since_last_sell < 20:
                buy_gate_open = False
            elif days_since_last_sell < 60:
                pattern_a = close > ma20_series[-1] and total_score > (buy_threshold - 5.0)
                pattern_b = (
                    len(recent_scores) >= 3
                    and recent_scores[-3] < recent_scores[-2] < recent_scores[-1]
                )
                buy_gate_open = pattern_a or pattern_b
                if buy_gate_open:
                    if pattern_a and pattern_b:
                        buy_reason = "both"
                    elif pattern_a:
                        buy_reason = "pattern_a"
                    else:
                        buy_reason = "pattern_b"
            else:
                buy_gate_open = True
                buy_reason = "day60"

            current_logic_sell = shares > 0 and sell_gate_open and not cooldown_active
            experimental_sell = (
                shares > 0
                and not cooldown_active
                and total_score >= sell_threshold
                and technical_threshold is not None
                and float(technical_score) >= technical_threshold
            )
            should_sell = current_logic_sell if rule_name == "current_logic" else experimental_sell
            if should_sell:
                trades.append(
                    {
                        "action": "SELL",
                        "date": date_str,
                        "quantity": shares,
                        "price": close,
                        "reason": (
                            "current_logic_sell"
                            if rule_name == "current_logic"
                            else f"experimental_total>={sell_threshold}_technical>={technical_threshold}"
                        ),
                    }
                )
                cash += shares * close
                shares = 0
                sell_cooldown_days_remaining = 30
                days_since_last_sell = 0
                if rule_name == "current_logic":
                    overheat_event_consumed = True
            elif shares == 0 and days_since_last_sell is not None and buy_gate_open:
                qty = floor(cash / close)
                if qty > 0:
                    cash -= qty * close
                    shares += qty
                    if buy_reason in buy_reason_counts:
                        buy_reason_counts[buy_reason] += 1
                    trades.append(
                        {
                            "action": "BUY",
                            "date": date_str,
                            "quantity": qty,
                            "price": close,
                            "reason": buy_reason,
                        }
                    )

        portfolio_values.append(cash + shares * close)

    final_price = price_history[-1][1]
    final_value = cash + shares * final_price
    buy_and_hold_final = hold_cash + hold_shares * final_price
    return {
        "final_value": round(final_value, 2),
        "buy_and_hold_final": round(buy_and_hold_final, 2),
        "max_drawdown_pct": _compute_max_drawdown(portfolio_values),
        "trades": trades,
        "price_history": price_history,
        "buy_reason_counts": buy_reason_counts,
    }


def run_experimental_rule(
    ctx: SimulationContext,
    *,
    index_type: str,
    technical_threshold: float,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    sell_threshold: float,
    score_ma: int,
) -> Dict:
    return _run_simulation_core(
        ctx,
        index_type=index_type,
        rule_name="experimental",
        sell_threshold=sell_threshold,
        technical_threshold=technical_threshold,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        buy_threshold=buy_threshold,
        score_ma=score_ma,
    )


def run_current_logic_rule(
    ctx: SimulationContext,
    *,
    index_type: str,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    sell_threshold: float,
    score_ma: int,
) -> Dict:
    return _run_simulation_core(
        ctx,
        index_type=index_type,
        rule_name="current_logic",
        sell_threshold=sell_threshold,
        technical_threshold=None,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        buy_threshold=buy_threshold,
        score_ma=score_ma,
    )


def run_comparison(
    *,
    ctx: SimulationContext,
    index_type: str,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    score_ma: int,
) -> List[Dict]:
    rows: List[Dict] = []
    for technical_threshold in (77.0, 78.0, 79.0, 80.0):
        result = run_experimental_rule(
            ctx,
            index_type=index_type,
            technical_threshold=technical_threshold,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            buy_threshold=buy_threshold,
            sell_threshold=70.0,
            score_ma=score_ma,
        )
        rows.append(
            _summarize_rule_result(
                f"experimental_total70_technical{int(technical_threshold)}", index_type, result
            )
        )

    return rows


def _build_context() -> SimulationContext:
    market_service = SP500MarketService()
    macro_service = MacroDataService()
    event_service = EventService(manual_events_path=ROOT_DIR / "data" / "us_events.json")
    backtest_service = BacktestService(market_service, macro_service, event_service)
    return SimulationContext(backtest_service=backtest_service)


def _output(rows: List[Dict], output_format: str, output_path: str | None):
    if output_format == "json":
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        if output_path:
            Path(output_path).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return

    header = list(rows[0].keys()) if rows else []
    out = Path(output_path).open("w", encoding="utf-8", newline="") if output_path else sys.stdout
    close_required = bool(output_path)
    try:
        writer = csv.DictWriter(out, fieldnames=header)
        writer.writeheader()
        for row in rows:
            serializable = dict(row)
            for key in ("sell_dates", "buy_dates", "sell_reasons", "buy_reasons", "sell_post_return_20d_pct", "buyback_return_pct"):
                serializable[key] = json.dumps(serializable.get(key, []), ensure_ascii=False)
            writer.writerow(serializable)
    finally:
        if close_required:
            out.close()


def main():
    parser = argparse.ArgumentParser(description="Offline experimental SELL rule simulator.")
    parser.add_argument("--index", default="SP500_JPY")
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--buy-threshold", type=float, default=40.0)
    parser.add_argument("--score-ma", type=int, default=200)
    parser.add_argument("--output-format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    ctx = _build_context()
    rows = run_comparison(
        ctx=ctx,
        index_type=args.index,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        initial_cash=args.initial_cash,
        buy_threshold=args.buy_threshold,
        score_ma=args.score_ma,
    )
    _output(rows, args.output_format, args.output)


if __name__ == "__main__":
    main()
