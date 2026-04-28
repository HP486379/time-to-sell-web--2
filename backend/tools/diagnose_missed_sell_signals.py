from __future__ import annotations

"""Missed-SELL diagnostics tool (offline only, fixed thresholds: SELL=80 / BUY=40)."""

import argparse
import csv
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import date
from math import floor
from pathlib import Path
from statistics import mean
from typing import Dict, List, Optional

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from scoring.events import calculate_event_adjustment
from scoring.macro import calculate_macro_score
from scoring.technical import calculate_technical_score, calculate_ultra_long_mas, moving_average
from services.backtest_service import BacktestService
from services.event_service import EventService
from services.macro_data_service import MacroDataService
from services.sp500_market_service import SP500MarketService

SELL_THRESHOLD = 80.0
BUY_THRESHOLD = 40.0
DEFAULT_INDEX_TYPES = [
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "NIFTY50",
    "ALLCOUNTRY",
    "ALLCOUNTRY_JPY",
]


@dataclass
class DiagnoseContext:
    backtest_service: BacktestService


def parse_index_types(raw: str | None) -> List[str]:
    if not raw:
        return list(DEFAULT_INDEX_TYPES)
    return [x.strip() for x in raw.split(",") if x.strip()]


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


def _forward_return(price_history: List[tuple[str, float]], idx: int, days: int) -> Optional[float]:
    if idx + days >= len(price_history):
        return None
    px0 = price_history[idx][1]
    px1 = price_history[idx + days][1]
    return round(((px1 / px0) - 1) * 100, 4)


def _forward_max_drawdown(price_history: List[tuple[str, float]], idx: int, days: int) -> Optional[float]:
    if idx + 1 >= len(price_history):
        return None
    end = min(idx + days, len(price_history) - 1)
    start_price = price_history[idx][1]
    lows = [price_history[i][1] for i in range(idx + 1, end + 1)]
    if not lows:
        return None
    min_price = min(lows)
    return round(((min_price / start_price) - 1) * 100, 4)


def _score_snapshot(
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
    event_adjustment, event_debug = calculate_event_adjustment(current_date, events)
    nearby_events = []
    for ev in event_debug.get("events", [])[:5]:
        nearby_events.append(
            {
                "date": ev.get("date").isoformat() if hasattr(ev.get("date"), "isoformat") else str(ev.get("date")),
                "event": ev.get("event"),
                "importance": ev.get("importance"),
            }
        )
    effective_event = event_debug.get("effective_event")
    event_adjustment_reason = "no_nearby_events"
    if event_adjustment != 0:
        event_adjustment_reason = "risk_weighted_penalty_applied"
    elif effective_event is not None:
        event_adjustment_reason = "nearby_events_but_zero_risk"
    total_score = float(svc._calculate_scores(sub_history, macro_series, current_date, score_ma))
    return {
        "total_score": total_score,
        "technical_score": float(technical_score),
        "macro_score": float(macro_score),
        "event_adjustment": float(event_adjustment),
        "event_adjustment_reason": event_adjustment_reason,
        "event_source_count": len(event_debug.get("events", [])),
        "nearby_events": nearby_events,
    }


def diagnose_index(
    ctx: DiagnoseContext,
    *,
    index_type: str,
    start_date: date,
    end_date: date,
    initial_cash: float,
    score_ma: int,
) -> Dict:
    svc = ctx.backtest_service
    raw_history = svc.market_service.get_price_history_range(
        start_date, end_date, allow_fallback=svc.allow_fallback, index_type=index_type
    )
    price_history = svc._prepare_price_history(raw_history, index_type)
    macro_series = svc.macro_service.get_macro_series_range(start_date, end_date)

    first_price = price_history[0][1]
    shares = floor(initial_cash / first_price)
    cash = initial_cash - shares * first_price

    sell_cooldown_days_remaining = 0
    days_since_last_sell: int | None = None
    overheat_event_date: str | None = None
    overheat_event_consumed = False
    prev_overheat_state = False
    recent_scores: List[float] = []

    details: List[Dict] = []

    for idx, (date_str, close) in enumerate(price_history):
        if sell_cooldown_days_remaining > 0:
            sell_cooldown_days_remaining -= 1
        if days_since_last_sell is not None:
            days_since_last_sell += 1

        if idx < max(score_ma - 1, 199):
            continue

        sub_history = price_history[: idx + 1]
        snapshot = _score_snapshot(svc, sub_history, macro_series, date.fromisoformat(date_str), score_ma)
        total_score = snapshot["total_score"]
        recent_scores.append(total_score)

        closes = [p[1] for p in sub_history]
        ma20_series = moving_average(closes, 20)
        ma50_series = moving_average(closes, 50)
        cooldown_active = sell_cooldown_days_remaining > 0
        is_overheat_today = total_score >= SELL_THRESHOLD
        if is_overheat_today and not prev_overheat_state:
            overheat_event_date = date_str
            overheat_event_consumed = False
        prev_overheat_state = is_overheat_today

        score_declining_3days = (
            len(recent_scores) >= 4 and recent_scores[-1] < recent_scores[-2] < recent_scores[-3] < recent_scores[-4]
        )
        close_below_ma20 = close < ma20_series[-1]
        peakout_detected = score_declining_3days and close_below_ma20
        close_below_ma20_2days = len(closes) >= 2 and close < ma20_series[-1] and closes[-2] < ma20_series[-2]
        close_below_ma50 = close < ma50_series[-1]
        confirmation_detected = close_below_ma20_2days or close_below_ma50
        overheat_event_active = overheat_event_date is not None and not overheat_event_consumed
        sell_gate_core = overheat_event_active and peakout_detected and confirmation_detected
        sell_gate_open = shares > 0 and not cooldown_active and sell_gate_core
        overheat_event_raw_conditions = {
            "is_overheat_today": is_overheat_today,
            "prev_overheat_state": prev_overheat_state,
            "overheat_event_date": overheat_event_date,
            "overheat_event_consumed": overheat_event_consumed,
            "overheat_event_active": overheat_event_active,
        }
        sell_gate_required_conditions = {
            "has_shares": shares > 0,
            "cooldown_clear": not cooldown_active,
            "overheat_event_active": overheat_event_active,
            "peakout_detected": peakout_detected,
            "confirmation_detected": confirmation_detected,
        }

        blockers: List[str] = []
        if not sell_gate_open:
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
        sell_gate_failed_conditions = [k for k, v in sell_gate_required_conditions.items() if not v]

        f20 = _forward_return(price_history, idx, 20)
        f60 = _forward_return(price_history, idx, 60)
        d20 = _forward_max_drawdown(price_history, idx, 20)
        d60 = _forward_max_drawdown(price_history, idx, 60)

        is_large_drop = (f20 is not None and f20 <= -5.0) or (f60 is not None and (f60 <= -8.0 or f60 <= -10.0))
        if is_large_drop:
            technical_high_total_shortage = snapshot["technical_score"] >= 70.0 and total_score < SELL_THRESHOLD
            technical_very_high_total_shortage = snapshot["technical_score"] >= 75.0 and total_score < SELL_THRESHOLD
            macro_drag_suspected = snapshot["macro_score"] < 45.0 and total_score < SELL_THRESHOLD
            event_adjustment_is_zero = abs(snapshot["event_adjustment"]) < 1e-9
            case_tags: List[str] = []
            if snapshot["technical_score"] >= 70.0 and (event_adjustment_is_zero or snapshot["macro_score"] < 50.0 or not sell_gate_open):
                case_tags.append("technical_high_but_macro_event_or_gate_blocked")
            if snapshot["macro_score"] >= 60.0 and snapshot["technical_score"] < 60.0 and total_score < SELL_THRESHOLD:
                case_tags.append("macro_high_but_technical_low")
            if event_adjustment_is_zero:
                case_tags.append("event_adjustment_zero")
            if "overheat_event_inactive" in blockers:
                case_tags.append("blocked_by_overheat_event_inactive")
            if "peakout_not_detected" in blockers:
                case_tags.append("blocked_by_peakout_not_detected")
            details.append(
                {
                    "index_type": index_type,
                    "date": date_str,
                    "close": close,
                    "total_score": round(total_score, 2),
                    "technical_score": round(snapshot["technical_score"], 2),
                    "macro_score": round(snapshot["macro_score"], 2),
                    "event_adjustment": round(snapshot["event_adjustment"], 2),
                    "event_adjustment_reason": snapshot["event_adjustment_reason"],
                    "event_source_count": snapshot["event_source_count"],
                    "nearby_events": snapshot["nearby_events"],
                    "score_shortage_to_80": round(max(0.0, SELL_THRESHOLD - total_score), 2),
                    "sell_gate_open": sell_gate_open,
                    "blockers": blockers,
                    "overheat_event_raw_conditions": overheat_event_raw_conditions,
                    "sell_gate_required_conditions": sell_gate_required_conditions,
                    "sell_gate_failed_conditions": sell_gate_failed_conditions,
                    "overheat_event_active": overheat_event_active,
                    "peakout_detected": peakout_detected,
                    "confirmation_detected": confirmation_detected,
                    "technical_high_total_shortage": technical_high_total_shortage,
                    "technical_very_high_total_shortage": technical_very_high_total_shortage,
                    "macro_drag_suspected": macro_drag_suspected,
                    "event_adjustment_is_zero": event_adjustment_is_zero,
                    "case_tags": case_tags,
                    "forward_20d_pct": f20,
                    "forward_60d_pct": f60,
                    "max_drawdown_next_20d": d20,
                    "max_drawdown_next_60d": d60,
                }
            )

        if sell_gate_open:
            cash += shares * close
            shares = 0
            sell_cooldown_days_remaining = 30
            days_since_last_sell = 0
            overheat_event_consumed = True
        elif shares == 0:
            buy_gate_open = False
            if days_since_last_sell is None:
                buy_gate_open = total_score < BUY_THRESHOLD
            elif days_since_last_sell < 20:
                buy_gate_open = False
            elif days_since_last_sell < 60:
                pattern_a = close > ma20_series[-1] and total_score > (BUY_THRESHOLD - 5.0)
                pattern_b = len(recent_scores) >= 3 and recent_scores[-3] < recent_scores[-2] < recent_scores[-1]
                buy_gate_open = pattern_a or pattern_b
            else:
                buy_gate_open = True
            if buy_gate_open:
                qty = floor(cash / close)
                if qty > 0:
                    cash -= qty * close
                    shares += qty

    blocker_counter = Counter()
    for row in details:
        blocker_counter.update(row["blockers"])

    summary = {
        "index_type": index_type,
        "large_drop_candidate_count": len(details),
        "event_adjustment_nonzero_count": sum(1 for d in details if not d["event_adjustment_is_zero"]),
        "overheat_event_inactive_count": sum(1 for d in details if "overheat_event_inactive" in d["blockers"]),
        "peakout_not_detected_count": sum(1 for d in details if "peakout_not_detected" in d["blockers"]),
        "confirmation_not_detected_count": sum(1 for d in details if "confirmation_not_detected" in d["blockers"]),
        "avg_total_score_before_large_drop": round(mean([d["total_score"] for d in details]), 2) if details else 0.0,
        "max_total_score_before_large_drop": round(max([d["total_score"] for d in details]), 2) if details else 0.0,
        "p95_total_score_before_large_drop": round(_percentile([d["total_score"] for d in details], 95), 2) if details else 0.0,
        "avg_score_shortage_to_80": round(mean([d["score_shortage_to_80"] for d in details]), 2) if details else 0.0,
        "avg_technical_score": round(mean([d["technical_score"] for d in details]), 2) if details else 0.0,
        "avg_macro_score": round(mean([d["macro_score"] for d in details]), 2) if details else 0.0,
        "avg_event_adjustment": round(mean([d["event_adjustment"] for d in details]), 2) if details else 0.0,
        "sell_gate_open_count": sum(1 for d in details if d["sell_gate_open"]),
        "technical_ge70_total_lt80_count": sum(1 for d in details if d["technical_high_total_shortage"]),
        "technical_ge75_total_lt80_count": sum(1 for d in details if d["technical_very_high_total_shortage"]),
        "macro_drag_suspected_count": sum(1 for d in details if d["macro_drag_suspected"]),
        "technical_high_but_macro_event_or_gate_blocked_count": sum(
            1 for d in details if "technical_high_but_macro_event_or_gate_blocked" in d["case_tags"]
        ),
        "macro_high_but_technical_low_count": sum(1 for d in details if "macro_high_but_technical_low" in d["case_tags"]),
        "event_adjustment_zero_large_drop_count": sum(1 for d in details if "event_adjustment_zero" in d["case_tags"]),
        "overheat_event_inactive_blocked_count": sum(
            1 for d in details if "blocked_by_overheat_event_inactive" in d["case_tags"]
        ),
        "peakout_not_detected_blocked_count": sum(
            1 for d in details if "blocked_by_peakout_not_detected" in d["case_tags"]
        ),
        "most_common_blockers": [{"blocker": k, "count": v} for k, v in blocker_counter.most_common(5)],
    }
    return {"summary": summary, "details": details}


def run_diagnosis(
    *,
    ctx: DiagnoseContext,
    indices: List[str],
    start_date: date,
    end_date: date,
    initial_cash: float,
    score_ma: int,
) -> Dict:
    summaries: List[Dict] = []
    details: List[Dict] = []
    for index_type in indices:
        res = diagnose_index(
            ctx,
            index_type=index_type,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            score_ma=score_ma,
        )
        summaries.append(res["summary"])
        details.extend(res["details"])
    return {"summaries": summaries, "details": details}


def _output(payload: Dict, output_format: str, output_path: str | None):
    if output_format == "json":
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        if output_path:
            Path(output_path).write_text(text, encoding="utf-8")
        else:
            print(text)
        return

    rows: List[Dict] = []
    for row in payload.get("summaries", []):
        rows.append({"record_type": "summary", **row})
    for row in payload.get("details", []):
        rows.append({"record_type": "detail", **row})

    header: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in header:
                header.append(k)
    out = Path(output_path).open("w", encoding="utf-8", newline="") if output_path else sys.stdout
    close_required = bool(output_path)
    try:
        writer = csv.DictWriter(out, fieldnames=header)
        writer.writeheader()
        for r in rows:
            obj = dict(r)
            for k in (
                "blockers",
                "most_common_blockers",
                "case_tags",
                "nearby_events",
                "overheat_event_raw_conditions",
                "sell_gate_required_conditions",
                "sell_gate_failed_conditions",
            ):
                if k in obj:
                    obj[k] = json.dumps(obj[k], ensure_ascii=False)
            writer.writerow(obj)
    finally:
        if close_required:
            out.close()


def _build_context() -> DiagnoseContext:
    market_service = SP500MarketService()
    macro_service = MacroDataService()
    event_service = EventService(manual_events_path=ROOT_DIR / "data" / "us_events.json")
    backtest_service = BacktestService(market_service, macro_service, event_service)
    return DiagnoseContext(backtest_service=backtest_service)


def main():
    parser = argparse.ArgumentParser(description="Diagnose missed large-drop SELL signals with fixed 80/40 thresholds.")
    parser.add_argument("--indices", default=None)
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--score-ma", type=int, default=200)
    parser.add_argument("--output-format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    ctx = _build_context()
    payload = run_diagnosis(
        ctx=ctx,
        indices=parse_index_types(args.indices),
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        initial_cash=args.initial_cash,
        score_ma=args.score_ma,
    )
    _output(payload, args.output_format, args.output)


if __name__ == "__main__":
    main()
