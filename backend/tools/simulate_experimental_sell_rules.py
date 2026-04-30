from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import date
from math import floor
from pathlib import Path
from statistics import mean, median
from collections import Counter
from typing import Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scoring.technical import calculate_technical_score, moving_average
from scoring.technical import calculate_ultra_long_attenuation, calculate_ultra_long_mas, clip
from scoring.macro import calculate_macro_score
from scoring.events import calculate_event_adjustment
from services.backtest_service import BacktestService
from services.event_service import EventService
from services.macro_data_service import MacroDataService
from services.sp500_market_service import SP500MarketService


@dataclass
class SimulationContext:
    backtest_service: BacktestService


@dataclass
class CalibrationConfig:
    multiplier: float = 1.0
    offset: float = 0.0


@dataclass
class WeightAdjustConfig:
    technical_weight: float = 0.7
    macro_weight: float = 0.3
    event_weight: float = 1.0
    scale: float = 1.0


DEFAULT_INDEX_TYPES = [
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "NIFTY50",
    "ALLCOUNTRY",
    "ALLCOUNTRY_JPY",
]

PORTFOLIO_RULES: Dict[str, Dict[str, str]] = {
    "current_all": {},
    "jpy_conservative": {
        "SP500_JPY": "no_ath_penalty_current_gate",
        "ALLCOUNTRY_JPY": "no_ath_penalty_current_gate",
    },
    "jpy_aggressive": {
        "SP500_JPY": "ath_boost_8_score80_gate",
        "ALLCOUNTRY_JPY": "no_ath_penalty_score80_gate",
    },
    "sp500_jpy_only": {
        "SP500_JPY": "ath_boost_8_score80_gate",
    },
    "allcountry_jpy_only": {
        "ALLCOUNTRY_JPY": "no_ath_penalty_score80_gate",
    },
    # aliases for decision-friendly plans
    "safe_sp500jpy_only": {
        "SP500_JPY": "ath_boost_8_score80_gate",
    },
    "aggressive_jpy_dual": {
        "SP500_JPY": "ath_boost_8_score80_gate",
        "ALLCOUNTRY_JPY": "no_ath_penalty_score80_gate",
    },
}


def _safe_avg(values: List[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


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


def parse_index_types(raw: str | None) -> List[str]:
    if not raw:
        return list(DEFAULT_INDEX_TYPES)
    parts = [p.strip() for p in raw.split(",")]
    return [p for p in parts if p]


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
        "score_max_before": result.get("score_max_before"),
        "score_max_after": result.get("score_max_after"),
        "score_p95_before": result.get("score_p95_before"),
        "score_p95_after": result.get("score_p95_after"),
        "score_distribution_before": result.get("score_distribution_before"),
        "score_distribution_after": result.get("score_distribution_after"),
        "score_max": result.get("score_max"),
        "score_p95": result.get("score_p95"),
        "score_p99": result.get("score_p99"),
        "score_ge_80_count": result.get("score_ge_80_count"),
        "score_ge_80_dates": result.get("score_ge_80_dates", []),
        "score_ge_80_sell_gate_details": result.get("score_ge_80_sell_gate_details", []),
        "score_ge_80_forward_20d_pct": result.get("score_ge_80_forward_20d_pct", []),
        "score_ge_80_forward_60d_pct": result.get("score_ge_80_forward_60d_pct", []),
        "actual_sell_dates": result.get("actual_sell_dates", []),
        "sell_loss_reasons": result.get("sell_loss_reasons", []),
        "sell_gate_blockers": result.get("sell_gate_blockers", {}),
        "blocked_good_sell_candidate_count": result.get("blocked_good_sell_candidate_count", 0),
        "bad_sell_count": result.get("bad_sell_count", 0),
    }


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * (p / 100.0)
    lo = int(rank)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = rank - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def _score_distribution(values: List[float]) -> Dict[str, float]:
    if not values:
        return {
            "min": 0.0,
            "max": 0.0,
            "average": 0.0,
            "median": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p97": 0.0,
            "p99": 0.0,
        }
    return {
        "min": round(min(values), 2),
        "max": round(max(values), 2),
        "average": round(mean(values), 2),
        "median": round(float(median(values)), 2),
        "p90": round(_percentile(values, 90), 2),
        "p95": round(_percentile(values, 95), 2),
        "p97": round(_percentile(values, 97), 2),
        "p99": round(_percentile(values, 99), 2),
    }


def _build_calibration_config(values: List[float]) -> CalibrationConfig:
    p95 = _percentile(values, 95)
    if p95 <= 0:
        return CalibrationConfig()
    multiplier = 80.0 / p95
    multiplier = max(0.7, min(multiplier, 2.0))
    offset = 80.0 - (p95 * multiplier)
    return CalibrationConfig(multiplier=round(multiplier, 4), offset=round(offset, 4))


def _build_weight_adjust_config(score_components: List[Dict[str, float]]) -> WeightAdjustConfig:
    if not score_components:
        return WeightAdjustConfig()
    p95_technical = _percentile([s["technical_score"] for s in score_components], 95)
    p95_macro = _percentile([s["macro_score"] for s in score_components], 95)
    p95_event = _percentile([s["event_adjustment"] for s in score_components], 95)
    denom = max(p95_technical + p95_macro, 1e-9)
    technical_weight = max(0.55, min(0.85, 0.5 + 0.4 * (p95_technical / denom)))
    macro_weight = 1.0 - technical_weight
    projected_p95 = (technical_weight * p95_technical) + (macro_weight * p95_macro) + p95_event
    scale = 80.0 / projected_p95 if projected_p95 > 0 else 1.0
    scale = max(0.7, min(scale, 1.8))
    return WeightAdjustConfig(
        technical_weight=round(technical_weight, 4),
        macro_weight=round(macro_weight, 4),
        event_weight=1.0,
        scale=round(scale, 4),
    )


def _calculate_score_snapshot(
    svc: BacktestService,
    sub_history: List[tuple[str, float]],
    macro_series: Dict[str, List[tuple[date, float]]],
    current_date: date,
    score_ma: int,
) -> Dict[str, float]:
    technical_score, _ = calculate_technical_score(sub_history, base_window=score_ma)
    r_hist, r_cur = svc._history_and_current(macro_series["r_10y"], current_date)
    cpi_hist, cpi_cur = svc._history_and_current(macro_series["cpi"], current_date)
    vix_hist, vix_cur = svc._history_and_current(macro_series["vix"], current_date)
    macro_score, _ = calculate_macro_score((r_hist, r_cur), (cpi_hist, cpi_cur), (vix_hist, vix_cur))
    events = svc.event_service.get_events_for_date(current_date)
    event_adjustment, _ = calculate_event_adjustment(current_date, events)
    ma500, ma1000 = calculate_ultra_long_mas(sub_history)
    current_price = sub_history[-1][1] if sub_history else None
    total_score = float(
        svc._calculate_scores(sub_history, macro_series, current_date, score_ma)
    )
    return {
        "technical_score": float(technical_score),
        "macro_score": float(macro_score),
        "event_adjustment": float(event_adjustment),
        "ma500": ma500,
        "ma1000": ma1000,
        "current_price": current_price,
        "total_score_raw": total_score,
    }


def _apply_technical_variant(rule_name: str, technical_score: float, closes: List[float]) -> float:
    adjusted = technical_score
    variant_base = rule_name
    if "_current_gate" in rule_name:
        variant_base = rule_name.replace("_current_gate", "")
    if "_score80_gate" in rule_name:
        variant_base = rule_name.replace("_score80_gate", "")
    if "_relaxed_gate" in rule_name:
        variant_base = rule_name.replace("_relaxed_gate", "")
    is_60d_high = len(closes) >= 60 and closes[-1] >= max(closes[-60:])
    is_strong_uptrend = len(closes) >= 20 and closes[-1] > closes[-20]
    if variant_base in {"no_ath_penalty", "no_ath_penalty_plus_no_uptrend_penalty"} and is_60d_high:
        adjusted += 12.0
    if variant_base == "ath_boost_6" and is_60d_high:
        adjusted += 6.0
    if variant_base == "ath_boost_8" and is_60d_high:
        adjusted += 8.0
    if variant_base in {"no_uptrend_penalty", "no_ath_penalty_plus_no_uptrend_penalty"} and is_strong_uptrend:
        adjusted += 6.0
    return float(clip(adjusted))


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
    calibration_config: CalibrationConfig | None = None,
    weight_adjust_config: WeightAdjustConfig | None = None,
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
    score_before_values: List[float] = []
    score_after_values: List[float] = []
    score_ge_80_events: List[Dict] = []
    sell_gate_blockers_counter: Counter[str] = Counter()
    blocked_good_sell_candidate_count = 0

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
            snapshot = _calculate_score_snapshot(
                svc, sub_history, macro_series, date.fromisoformat(date_str), score_ma
            )
            raw_total_score = snapshot["total_score_raw"]
            total_score = raw_total_score
            technical_score = snapshot["technical_score"]
            closes = [p[1] for p in sub_history]
            if any(x in rule_name for x in ("no_ath_penalty", "ath_boost_6", "ath_boost_8", "no_uptrend_penalty")):
                technical_score = _apply_technical_variant(rule_name, technical_score, closes)
                weighted_raw = (0.7 * technical_score) + (0.3 * snapshot["macro_score"]) + snapshot["event_adjustment"]
                attenuation = calculate_ultra_long_attenuation(
                    snapshot["current_price"], snapshot["ma500"], snapshot["ma1000"]
                )
                total_score = clip(weighted_raw * (attenuation if attenuation is not None else 1.0))
            if weight_adjust_config is not None:
                weighted_raw = (
                    (weight_adjust_config.technical_weight * snapshot["technical_score"])
                    + (weight_adjust_config.macro_weight * snapshot["macro_score"])
                    + (weight_adjust_config.event_weight * snapshot["event_adjustment"])
                )
                attenuation = calculate_ultra_long_attenuation(
                    snapshot["current_price"], snapshot["ma500"], snapshot["ma1000"]
                )
                total_score = clip(weighted_raw * weight_adjust_config.scale * (attenuation if attenuation is not None else 1.0))
            elif calibration_config is not None:
                total_score = clip((raw_total_score * calibration_config.multiplier) + calibration_config.offset)

            score_before_values.append(float(raw_total_score))
            score_after_values.append(float(total_score))
            recent_scores.append(total_score)
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
            gate_mode = "current_gate"
            if rule_name.endswith("_score80_gate"):
                gate_mode = "score80_gate"
            elif rule_name.endswith("_relaxed_gate"):
                gate_mode = "relaxed_gate"

            if total_score >= 80.0:
                blockers: List[str] = []
                if shares <= 0:
                    blockers.append("no_shares")
                if cooldown_active:
                    blockers.append("cooldown_active")
                if not overheat_event_active:
                    blockers.append("overheat_event_inactive")
                if not peakout_detected:
                    blockers.append("peakout_not_detected")
                if not confirmation_detected:
                    blockers.append("confirmation_not_detected")
                for b in blockers:
                    sell_gate_blockers_counter[b] += 1
                fwd20 = None
                fwd60 = None
                if idx + 20 < len(price_history):
                    fwd20 = round(((price_history[idx + 20][1] / close) - 1) * 100, 4)
                if idx + 60 < len(price_history):
                    fwd60 = round(((price_history[idx + 60][1] / close) - 1) * 100, 4)
                score_ge_80_events.append(
                    {
                        "date": date_str,
                        "sell_gate_open": sell_gate_open and not cooldown_active and shares > 0,
                        "blockers": blockers,
                        "forward_20d_pct": fwd20,
                        "forward_60d_pct": fwd60,
                    }
                )
                if not (shares > 0 and not cooldown_active and sell_gate_open) and fwd20 is not None and fwd20 <= -5.0:
                    blocked_good_sell_candidate_count += 1

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
            if gate_mode == "score80_gate":
                current_logic_sell = shares > 0 and not cooldown_active and total_score >= sell_threshold
            elif gate_mode == "relaxed_gate":
                current_logic_sell = (
                    shares > 0
                    and not cooldown_active
                    and total_score >= sell_threshold
                    and (peakout_detected or confirmation_detected)
                )
            experimental_sell = (
                shares > 0
                and not cooldown_active
                and total_score >= sell_threshold
                and technical_threshold is not None
                and float(technical_score) >= technical_threshold
            )
            should_sell = current_logic_sell if technical_threshold is None else experimental_sell
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
                if technical_threshold is None:
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
    score_ge_80_dates = [e["date"] for e in score_ge_80_events]
    score_ge_80_forward_20d_pct = [e["forward_20d_pct"] for e in score_ge_80_events if e["forward_20d_pct"] is not None]
    score_ge_80_forward_60d_pct = [e["forward_60d_pct"] for e in score_ge_80_events if e["forward_60d_pct"] is not None]
    actual_sell_dates = [t["date"] for t in trades if t["action"] == "SELL"]
    index_by_date = {dt: i for i, (dt, _) in enumerate(price_history)}
    sell_loss_reasons: List[Dict] = []
    bad_sell_count = 0
    for t in trades:
        if t["action"] != "SELL":
            continue
        i = index_by_date.get(t["date"])
        if i is None or i + 20 >= len(price_history):
            continue
        post20 = round(((price_history[i + 20][1] / t["price"]) - 1) * 100, 4)
        if post20 > 0:
            bad_sell_count += 1
            sell_loss_reasons.append(
                {
                    "date": t["date"],
                    "reason": "rebounded_after_sell_20d",
                    "post20_return_pct": post20,
                }
            )
    return {
        "final_value": round(final_value, 2),
        "buy_and_hold_final": round(buy_and_hold_final, 2),
        "max_drawdown_pct": _compute_max_drawdown(portfolio_values),
        "trades": trades,
        "price_history": price_history,
        "buy_reason_counts": buy_reason_counts,
        "score_max_before": round(max(score_before_values), 2) if score_before_values else 0.0,
        "score_max_after": round(max(score_after_values), 2) if score_after_values else 0.0,
        "score_p95_before": round(_percentile(score_before_values, 95), 2) if score_before_values else 0.0,
        "score_p95_after": round(_percentile(score_after_values, 95), 2) if score_after_values else 0.0,
        "score_distribution_before": _score_distribution(score_before_values),
        "score_distribution_after": _score_distribution(score_after_values),
        "score_max": round(max(score_after_values), 2) if score_after_values else 0.0,
        "score_p95": round(_percentile(score_after_values, 95), 2) if score_after_values else 0.0,
        "score_p99": round(_percentile(score_after_values, 99), 2) if score_after_values else 0.0,
        "score_ge_80_count": len(score_ge_80_events),
        "score_ge_80_dates": score_ge_80_dates,
        "score_ge_80_sell_gate_details": score_ge_80_events,
        "score_ge_80_forward_20d_pct": score_ge_80_forward_20d_pct,
        "score_ge_80_forward_60d_pct": score_ge_80_forward_60d_pct,
        "actual_sell_dates": actual_sell_dates,
        "sell_loss_reasons": sell_loss_reasons,
        "sell_gate_blockers": dict(sell_gate_blockers_counter),
        "blocked_good_sell_candidate_count": blocked_good_sell_candidate_count,
        "bad_sell_count": bad_sell_count,
    }


def run_calibrated_rule(
    ctx: SimulationContext,
    *,
    index_type: str,
    calibration_config: CalibrationConfig,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    sell_threshold: float,
    score_ma: int,
) -> Dict:
    # NOTE(deprecated):
    # index別 multiplier/offset 補正は全指数共通方針としては採用しないため、
    # 既定の比較フロー（run_comparison）では呼ばない。
    return _run_simulation_core(
        ctx,
        index_type=index_type,
        rule_name="index_calibrated_score",
        sell_threshold=sell_threshold,
        technical_threshold=None,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        buy_threshold=buy_threshold,
        score_ma=score_ma,
        calibration_config=calibration_config,
    )


def run_weight_adjusted_rule(
    ctx: SimulationContext,
    *,
    index_type: str,
    weight_adjust_config: WeightAdjustConfig,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    sell_threshold: float,
    score_ma: int,
) -> Dict:
    # NOTE(deprecated):
    # index別 weight/scale 補正は全指数共通方針としては採用しないため、
    # 既定の比較フロー（run_comparison）では呼ばない。
    return _run_simulation_core(
        ctx,
        index_type=index_type,
        rule_name="index_weight_adjusted_score",
        sell_threshold=sell_threshold,
        technical_threshold=None,
        start_date=start_date,
        end_date=end_date,
        initial_cash=initial_cash,
        buy_threshold=buy_threshold,
        score_ma=score_ma,
        weight_adjust_config=weight_adjust_config,
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
    rules = [
        "current_logic",
        "no_ath_penalty_current_gate",
        "ath_boost_8_current_gate",
        "no_ath_penalty_score80_gate",
        "ath_boost_8_score80_gate",
        "no_ath_penalty_relaxed_gate",
        "ath_boost_8_relaxed_gate",
    ]
    rows: List[Dict] = []
    for rule_name in rules:
        result = _run_simulation_core(
            ctx,
            index_type=index_type,
            rule_name=rule_name,
            sell_threshold=80.0,
            technical_threshold=None,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            buy_threshold=40.0,
            score_ma=score_ma,
        )
        rows.append(_summarize_rule_result(rule_name, index_type, result))
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
            for key in (
                "sell_dates",
                "buy_dates",
                "sell_reasons",
                "buy_reasons",
                "sell_post_return_20d_pct",
                "buyback_return_pct",
                "score_distribution_before",
                "score_distribution_after",
                "score_ge_80_dates",
                "score_ge_80_sell_gate_details",
                "score_ge_80_forward_20d_pct",
                "score_ge_80_forward_60d_pct",
                "actual_sell_dates",
                "sell_loss_reasons",
            ):
                serializable[key] = json.dumps(serializable.get(key, []), ensure_ascii=False)
            writer.writerow(serializable)
    finally:
        if close_required:
            out.close()


def build_portfolio_rule_comparison_from_json(input_json: str) -> Dict:
    rows = json.loads(Path(input_json).read_text(encoding="utf-8"))
    by_key = {(r["index_type"], r["rule_name"]): r for r in rows}
    index_types = sorted({r["index_type"] for r in rows})
    details: List[Dict] = []
    summaries: List[Dict] = []

    for portfolio_rule_name, overrides in PORTFOLIO_RULES.items():
        missing_items: List[Dict] = []
        total_diff_pct = 0.0
        win = lose = flat = 0
        total_bad_sell_count = 0
        total_trade_count = 0
        for index_type in index_types:
            applied_rule_name = overrides.get(index_type, "current_logic")
            row = by_key.get((index_type, applied_rule_name))
            if row is None:
                missing_items.append({"index_type": index_type, "rule_name": applied_rule_name})
                continue
            diff_pct = float(row.get("diff_pct", 0.0))
            total_diff_pct += diff_pct
            if diff_pct > 0:
                win += 1
            elif diff_pct < 0:
                lose += 1
            else:
                flat += 1
            total_bad_sell_count += int(row.get("bad_sell_count", 0))
            total_trade_count += int(row.get("trade_count", 0))
            details.append(
                {
                    "portfolio_rule_name": portfolio_rule_name,
                    "index_type": index_type,
                    "applied_rule_name": applied_rule_name,
                    "final_equity": row.get("final_equity"),
                    "hold_equity": row.get("hold_equity"),
                    "diff_pct": row.get("diff_pct"),
                    "trade_count": row.get("trade_count"),
                    "sell_count": row.get("sell_count"),
                    "buy_count": row.get("buy_count"),
                    "sell_dates": row.get("sell_dates", []),
                    "buy_dates": row.get("buy_dates", []),
                    "sell_post_return_20d_pct": row.get("sell_post_return_20d_pct", []),
                    "buyback_return_pct": row.get("buyback_return_pct", []),
                    "bad_sell_count": row.get("bad_sell_count", 0),
                    "blocked_good_sell_candidate_count": row.get("blocked_good_sell_candidate_count", 0),
                    "max_drawdown": row.get("max_drawdown"),
                }
            )
        summaries.append(
            {
                "portfolio_rule_name": portfolio_rule_name,
                "total_diff_pct": round(total_diff_pct, 4),
                "win_index_count": win,
                "lose_index_count": lose,
                "flat_index_count": flat,
                "total_bad_sell_count": total_bad_sell_count,
                "total_trade_count": total_trade_count,
                "missing_count": len(missing_items),
                "missing_items": missing_items,
            }
        )
    return {"summary": summaries, "details": details}


def build_index_rule_review_from_json(input_json: str) -> Dict:
    rows = json.loads(Path(input_json).read_text(encoding="utf-8"))
    by_index: Dict[str, List[Dict]] = {}
    for r in rows:
        by_index.setdefault(r["index_type"], []).append(r)

    details: List[Dict] = []
    summary: List[Dict] = []
    for index_type, idx_rows in by_index.items():
        ranked = sorted(idx_rows, key=lambda x: float(x.get("diff_pct", 0.0)), reverse=True)
        rank_map = {id(row): i + 1 for i, row in enumerate(ranked)}
        for row in idx_rows:
            details.append(
                {
                    "index_type": index_type,
                    "rule_name": row.get("rule_name"),
                    "final_equity": row.get("final_equity"),
                    "hold_equity": row.get("hold_equity"),
                    "diff_pct": row.get("diff_pct"),
                    "trade_count": row.get("trade_count"),
                    "sell_count": row.get("sell_count"),
                    "buy_count": row.get("buy_count"),
                    "sell_dates": row.get("sell_dates", []),
                    "buy_dates": row.get("buy_dates", []),
                    "sell_post_return_20d_pct": row.get("sell_post_return_20d_pct", []),
                    "buyback_return_pct": row.get("buyback_return_pct", []),
                    "bad_sell_count": row.get("bad_sell_count", 0),
                    "blocked_good_sell_candidate_count": row.get("blocked_good_sell_candidate_count", 0),
                    "max_drawdown": row.get("max_drawdown"),
                    "rank_by_diff_pct": rank_map[id(row)],
                }
            )

        current = next((r for r in idx_rows if r.get("rule_name") == "current_logic"), None)
        if current is None:
            summary.append(
                {
                    "index_type": index_type,
                    "current_rule_name": "current_logic",
                    "recommended_rule_name": None,
                    "recommendation": "needs_review",
                    "reason": "current_logic_missing",
                    "current_diff_pct": None,
                    "best_diff_pct": float(ranked[0].get("diff_pct", 0.0)) if ranked else 0.0,
                    "improvement_vs_current": None,
                    "current_bad_sell_count": None,
                    "best_bad_sell_count": int(ranked[0].get("bad_sell_count", 0)) if ranked else 0,
                    "current_trade_count": None,
                    "best_trade_count": int(ranked[0].get("trade_count", 0)) if ranked else 0,
                    "missing_items": [{"index_type": index_type, "rule_name": "current_logic"}],
                }
            )
            continue

        current_diff = float(current.get("diff_pct", 0.0))
        current_bad = int(current.get("bad_sell_count", 0))
        current_trade = int(current.get("trade_count", 0))
        best = ranked[0]
        best_diff = float(best.get("diff_pct", 0.0))
        best_bad = int(best.get("bad_sell_count", 0))
        best_trade = int(best.get("trade_count", 0))
        improvement = best_diff - current_diff
        avg_sell_post = _safe_avg([float(x) for x in best.get("sell_post_return_20d_pct", [])])

        recommendation = "keep_current"
        reason = "no_material_improvement"
        if best.get("rule_name") == "current_logic":
            recommendation = "keep_current"
            reason = "current_is_best"
        elif improvement <= 0.2:
            recommendation = "keep_current"
            reason = "improvement_too_small"
        elif best_bad > current_bad + 1 or best_trade > max(current_trade * 3, current_trade + 5):
            recommendation = "needs_review"
            reason = "risk_increase_too_large"
        elif index_type in {"TOPIX", "NIKKEI225", "NIFTY50"} and "score80_gate" in str(best.get("rule_name")) and best_diff < current_diff + 2.0:
            recommendation = "needs_review"
            reason = "score80_gate_not_safe_enough_for_index"
        elif avg_sell_post > 0.5:
            recommendation = "needs_review"
            reason = "post_sell_20d_not_favorable"
        elif best_diff < 0:
            recommendation = "reject_all"
            reason = "all_rules_underperform_hold"
        else:
            recommendation = "adopt"
            reason = "improved_diff_with_acceptable_risk"
        if index_type == "ALLCOUNTRY_JPY" and best_bad > 0:
            recommendation = "needs_review"
            reason = "has_bad_sell_cases_needs_review"

        summary.append(
            {
                "index_type": index_type,
                "current_rule_name": "current_logic",
                "recommended_rule_name": best.get("rule_name"),
                "recommendation": recommendation,
                "reason": reason,
                "current_diff_pct": current_diff,
                "best_diff_pct": best_diff,
                "improvement_vs_current": round(improvement, 4),
                "current_bad_sell_count": current_bad,
                "best_bad_sell_count": best_bad,
                "current_trade_count": current_trade,
                "best_trade_count": best_trade,
                "missing_items": [],
            }
        )
    return {"summary": summary, "details": details}


def build_allcountry_jpy_bad_sell_review_from_json(
    input_json: str,
    *,
    index_type: str = "ALLCOUNTRY_JPY",
    rule_name: str = "no_ath_penalty_score80_gate",
) -> Dict:
    rows = json.loads(Path(input_json).read_text(encoding="utf-8"))
    row = next((r for r in rows if r.get("index_type") == index_type and r.get("rule_name") == rule_name), None)
    if row is None:
        raise ValueError(f"missing_target_row:{index_type}:{rule_name}")

    sells = row.get("sell_dates", [])
    buys = row.get("buy_dates", [])
    sell_post = row.get("sell_post_return_20d_pct", [])
    buyback = row.get("buyback_return_pct", [])
    price_history = row.get("price_history", [])
    price_by_date = {d: p for d, p in price_history} if isinstance(price_history, list) else {}

    reviews: List[Dict] = []
    for i, sell_date in enumerate(sells):
        buy_date = buys[i] if i < len(buys) else None
        sell_post_20 = sell_post[i] if i < len(sell_post) else None
        buyback_ret = buyback[i] if i < len(buyback) else None
        is_bad_sell = (sell_post_20 is not None and float(sell_post_20) > 0) or (buyback_ret is not None and float(buyback_ret) > 0)
        bad_sell_reason = "post_sell_rebound" if is_bad_sell else ""
        memo = "review_needed" if is_bad_sell else "effective_sell"
        reviews.append(
            {
                "index_type": index_type,
                "rule_name": rule_name,
                "sell_date": sell_date,
                "buy_date": buy_date,
                "sell_price": price_by_date.get(sell_date),
                "buy_price": price_by_date.get(buy_date) if buy_date else None,
                "sell_total_score": None,
                "sell_technical_score": None,
                "sell_macro_score": None,
                "sell_event_adjustment": None,
                "sell_reason_flags": ["score80_gate", "no_ath_penalty"],
                "peakout_gate_result": None,
                "confirmation_gate_result": None,
                "score80_gate_result": True,
                "sell_post_return_20d_pct": sell_post_20,
                "buyback_return_pct": buyback_ret,
                "is_bad_sell": is_bad_sell,
                "bad_sell_reason": bad_sell_reason,
                "memo": memo,
            }
        )

    bad_count = sum(1 for r in reviews if r["is_bad_sell"])
    review_result = "acceptable_noise" if bad_count <= 1 and float(row.get("diff_pct", 0.0)) >= 8.0 else "too_risky"
    summary = {
        "index_type": index_type,
        "rule_name": rule_name,
        "recommendation_before_review": "needs_review",
        "total_diff_pct": row.get("diff_pct"),
        "bad_sell_count": row.get("bad_sell_count", bad_count),
        "trade_count": row.get("trade_count"),
        "review_result": review_result,
    }
    return {"summary": summary, "sell_reviews": reviews}


def _read_json_utf8(path: str) -> List[Dict]:
    text = Path(path).read_text(encoding="utf-8")
    return json.loads(text)


def build_three_index_sell_diagnostic_from_json(input_json: str) -> Dict:
    rows = _read_json_utf8(input_json)
    targets = {"TOPIX", "NIKKEI225", "NIFTY50"}
    details: List[Dict] = []
    summary: List[Dict] = []
    by_index: Dict[str, List[Dict]] = {}
    for r in rows:
        if r.get("index_type") in targets:
            by_index.setdefault(r["index_type"], []).append(r)

    for index_type in sorted(targets):
        idx_rows = by_index.get(index_type, [])
        current = next((r for r in idx_rows if r.get("rule_name") == "current_logic"), None)
        if current is None:
            summary.append(
                {
                    "index_type": index_type,
                    "sell_not_firing_main_reason": "current_logic_missing",
                    "bad_sell_main_reason": "unknown",
                    "improvement_focus": "data_completion_required",
                    "missing_items": [{"index_type": index_type, "rule_name": "current_logic"}],
                }
            )
            continue

        sell_dates = current.get("sell_dates", [])
        buy_dates = current.get("buy_dates", [])
        buyback = current.get("buyback_return_pct", [])
        sell_scores = current.get("score_ge_80_sell_gate_details", [])
        blockers = current.get("sell_gate_blockers", {})
        blocked_good = int(current.get("blocked_good_sell_candidate_count", 0))
        bad_sell_count = int(current.get("bad_sell_count", 0))

        for i, sd in enumerate(sell_dates):
            details.append(
                {
                    "index_type": index_type,
                    "section": "sell_buy_history",
                    "sell_date": sd,
                    "buy_date": buy_dates[i] if i < len(buy_dates) else None,
                    "sell_score": None,
                    "buy_score": None,
                    "buyback_return_pct": buyback[i] if i < len(buyback) else None,
                    "good_sell": not ((i < len(buyback)) and float(buyback[i]) > 0),
                    "bad_sell": (i < len(buyback)) and float(buyback[i]) > 0,
                }
            )

        for e in sell_scores:
            details.append(
                {
                    "index_type": index_type,
                    "section": "blocked_by_gate",
                    "date": e.get("date"),
                    "total_score": 80.0,
                    "technical_score": None,
                    "macro_score": None,
                    "event_adjustment": None,
                    "ath_penalty_applied": None,
                    "strong_uptrend_penalty_applied": None,
                    "gate_passed": bool(e.get("sell_gate_open")),
                    "gate_blockers": e.get("blockers", []),
                    "forward_20d_pct": e.get("forward_20d_pct"),
                    "forward_60d_pct": e.get("forward_60d_pct"),
                }
            )

        for b, cnt in blockers.items():
            details.append(
                {
                    "index_type": index_type,
                    "section": "gate_blocker_stats",
                    "blocker": b,
                    "count": cnt,
                }
            )

        sell_not_firing_reason = "score_not_reaching_80"
        if blocked_good > 0:
            sell_not_firing_reason = "gate_blocking_good_candidates"
        bad_sell_reason = "none"
        if bad_sell_count > 0:
            bad_sell_reason = "post_sell_rebound_noise"
        improvement_focus = "inspect_technical_components_and_gate" if blocked_good > 0 else "inspect_technical_macro_balance"
        summary.append(
            {
                "index_type": index_type,
                "sell_not_firing_main_reason": sell_not_firing_reason,
                "bad_sell_main_reason": bad_sell_reason,
                "improvement_focus": improvement_focus,
                "blocked_good_sell_candidate_count": blocked_good,
                "bad_sell_count": bad_sell_count,
                "trade_count": current.get("trade_count", 0),
                "missing_items": [],
            }
        )

    return {"summary": summary, "details": details}


def main():
    parser = argparse.ArgumentParser(description="Offline experimental SELL rule simulator.")
    parser.add_argument("--index", default=None, help="Single index_type to diagnose")
    parser.add_argument("--indices", default=None, help="Comma-separated index_type list")
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--buy-threshold", type=float, default=40.0)
    parser.add_argument("--score-ma", type=int, default=200)
    parser.add_argument("--output-format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default=None)
    parser.add_argument("--portfolio-rules", action="store_true")
    parser.add_argument("--review-index-rules", action="store_true")
    parser.add_argument("--review-allcountry-jpy", action="store_true")
    parser.add_argument("--diagnose-three-index", action="store_true")
    parser.add_argument("--input-json", default=None)
    parser.add_argument("--output-json", default=None)
    args = parser.parse_args()

    if args.portfolio_rules:
        if not args.input_json or not args.output_json:
            raise ValueError("--portfolio-rules requires --input-json and --output-json")
        payload = build_portfolio_rule_comparison_from_json(args.input_json)
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if args.review_index_rules:
        if not args.input_json or not args.output_json:
            raise ValueError("--review-index-rules requires --input-json and --output-json")
        payload = build_index_rule_review_from_json(args.input_json)
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if args.review_allcountry_jpy:
        if not args.input_json or not args.output_json:
            raise ValueError("--review-allcountry-jpy requires --input-json and --output-json")
        payload = build_allcountry_jpy_bad_sell_review_from_json(args.input_json)
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return
    if args.diagnose_three_index:
        if not args.input_json or not args.output_json:
            raise ValueError("--diagnose-three-index requires --input-json and --output-json")
        payload = build_three_index_sell_diagnostic_from_json(args.input_json)
        Path(args.output_json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return

    ctx = _build_context()
    if args.index:
        target_indices = [args.index]
    else:
        target_indices = parse_index_types(args.indices)
    rows: List[Dict] = []
    for index_type in target_indices:
        rows.extend(
            run_comparison(
                ctx=ctx,
                index_type=index_type,
                start_date=date.fromisoformat(args.start_date),
                end_date=date.fromisoformat(args.end_date),
                initial_cash=args.initial_cash,
                buy_threshold=args.buy_threshold,
                score_ma=args.score_ma,
            )
        )
    _output(rows, args.output_format, args.output)


if __name__ == "__main__":
    main()
