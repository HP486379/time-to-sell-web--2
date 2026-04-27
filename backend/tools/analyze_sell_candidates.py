from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from domain.index_type import normalize_index_type
from scoring.events import calculate_event_adjustment
from scoring.macro import calculate_macro_score
from scoring.technical import calculate_technical_score, calculate_ultra_long_mas
from scoring.total_score import calculate_total_score
from services.backtest_service import BacktestService
from services.event_service import EventService
from services.macro_data_service import MacroDataService
from services.sp500_market_service import SP500MarketService


DEFAULT_INDEX_TYPES = ["TOPIX", "SP500_JPY", "NIFTY50", "ALLCOUNTRY_JPY"]


@dataclass
class AnalysisContext:
    backtest_service: BacktestService
    market_service: SP500MarketService
    macro_service: MacroDataService
    event_service: EventService


def parse_index_types(raw: Optional[str]) -> List[str]:
    if not raw:
        return DEFAULT_INDEX_TYPES
    return [normalize_index_type(token.strip()) for token in raw.split(",") if token.strip()]


def _forward_return(price_history: List[tuple[str, float]], idx: int, days: int) -> Optional[float]:
    target_idx = idx + days
    if target_idx >= len(price_history):
        return None
    base = price_history[idx][1]
    target = price_history[target_idx][1]
    return round(((target / base) - 1) * 100, 4)


def _forward_max_drawdown(price_history: List[tuple[str, float]], idx: int, days: int) -> Optional[float]:
    start_idx = idx + 1
    end_idx = idx + days + 1
    if start_idx >= len(price_history):
        return None
    window = price_history[start_idx:end_idx]
    if not window:
        return None
    base = price_history[idx][1]
    min_price = min(price for _, price in window)
    return round(((min_price / base) - 1) * 100, 4)


def _summarize(rows: List[Dict]) -> Dict:
    post_20 = [row["post_return_20d_pct"] for row in rows if row["post_return_20d_pct"] is not None]
    post_60 = [row["post_return_60d_pct"] for row in rows if row["post_return_60d_pct"] is not None]
    neg20 = [value for value in post_20 if value < 0]
    neg60 = [value for value in post_60 if value < 0]
    actual_sell_count = sum(1 for row in rows if row["was_actual_sell"])

    def _avg(values: List[float]) -> Optional[float]:
        return round(sum(values) / len(values), 4) if values else None

    def _median(values: List[float]) -> Optional[float]:
        return round(float(statistics.median(values)), 4) if values else None

    return {
        "candidate_count": len(rows),
        "actual_sell_count": actual_sell_count,
        "avg_post_return_20d_pct": _avg(post_20),
        "avg_post_return_60d_pct": _avg(post_60),
        "median_post_return_20d_pct": _median(post_20),
        "median_post_return_60d_pct": _median(post_60),
        "negative_20d_count": len(neg20),
        "negative_60d_count": len(neg60),
        "negative_20d_ratio": round((len(neg20) / len(post_20)) * 100, 4) if post_20 else None,
        "negative_60d_ratio": round((len(neg60) / len(post_60)) * 100, 4) if post_60 else None,
        "worst_20d_pct": min(post_20) if post_20 else None,
        "worst_60d_pct": min(post_60) if post_60 else None,
        "best_20d_pct": max(post_20) if post_20 else None,
        "best_60d_pct": max(post_60) if post_60 else None,
    }


def _passes_filters(
    *,
    total_score: float,
    technical_score: float,
    macro_score: float,
    min_total_score: float,
    min_technical_score: Optional[float],
    min_macro_score: Optional[float],
) -> bool:
    if total_score < min_total_score:
        return False
    if min_technical_score is not None and technical_score < min_technical_score:
        return False
    if min_macro_score is not None and macro_score < min_macro_score:
        return False
    return True


def analyze_single_index(
    ctx: AnalysisContext,
    *,
    index_type: str,
    min_total_score: float,
    min_technical_score: Optional[float],
    min_macro_score: Optional[float],
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    score_ma: int,
) -> Dict:
    raw_history = ctx.market_service.get_price_history_range(
        start_date, end_date, allow_fallback=ctx.backtest_service.allow_fallback, index_type=index_type
    )
    price_history = ctx.backtest_service._prepare_price_history(raw_history, index_type)
    macro_series = ctx.macro_service.get_macro_series_range(start_date, end_date)

    backtest_result = ctx.backtest_service.run_backtest(
        start_date,
        end_date,
        initial_cash,
        buy_threshold,
        min_total_score,
        index_type,
        score_ma,
    )
    sell_events = backtest_result.get("diagnostics", {}).get("sell_events", [])
    sell_meta_by_date = {
        event.get("date"): {
            "sell_gate_open": event.get("sell_reason_flags", {}).get("sell_gate_open"),
            "sell_reason_flags": event.get("sell_reason_flags"),
        }
        for event in sell_events
        if isinstance(event, dict) and event.get("date")
    }

    rows: List[Dict] = []
    for idx, (date_str, close) in enumerate(price_history):
        if idx < max(score_ma - 1, 199):
            continue
        sub_history = price_history[: idx + 1]
        technical_score, _ = calculate_technical_score(sub_history, base_window=score_ma)
        r_hist, r_cur = ctx.backtest_service._history_and_current(
            macro_series["r_10y"], date.fromisoformat(date_str)
        )
        cpi_hist, cpi_cur = ctx.backtest_service._history_and_current(
            macro_series["cpi"], date.fromisoformat(date_str)
        )
        vix_hist, vix_cur = ctx.backtest_service._history_and_current(
            macro_series["vix"], date.fromisoformat(date_str)
        )
        macro_score, _ = calculate_macro_score((r_hist, r_cur), (cpi_hist, cpi_cur), (vix_hist, vix_cur))
        events = ctx.event_service.get_events_for_date(date.fromisoformat(date_str))
        event_adjustment, _ = calculate_event_adjustment(date.fromisoformat(date_str), events)
        ma500, ma1000 = calculate_ultra_long_mas(sub_history)
        total_score = calculate_total_score(
            technical_score,
            macro_score,
            event_adjustment,
            current_price=close,
            ma500=ma500,
            ma1000=ma1000,
        )

        if not _passes_filters(
            total_score=float(total_score),
            technical_score=float(technical_score),
            macro_score=float(macro_score),
            min_total_score=min_total_score,
            min_technical_score=min_technical_score,
            min_macro_score=min_macro_score,
        ):
            continue

        sell_meta = sell_meta_by_date.get(date_str, {})
        rows.append(
            {
                "index_type": index_type,
                "candidate_threshold": min_total_score,
                "date": date_str,
                "close": close,
                "total_score": round(float(total_score), 4),
                "technical_score": round(float(technical_score), 4),
                "macro_score": round(float(macro_score), 4),
                "event_adjustment": round(float(event_adjustment), 4),
                "was_actual_sell": date_str in sell_meta_by_date,
                "sell_gate_open": sell_meta.get("sell_gate_open"),
                "sell_reason_flags": sell_meta.get("sell_reason_flags"),
                "post_return_20d_pct": _forward_return(price_history, idx, 20),
                "post_return_60d_pct": _forward_return(price_history, idx, 60),
                "max_drawdown_next_20d_pct": _forward_max_drawdown(price_history, idx, 20),
                "max_drawdown_next_60d_pct": _forward_max_drawdown(price_history, idx, 60),
            }
        )

    return {
        "index_type": index_type,
        "threshold": min_total_score,
        "min_technical_score": min_technical_score,
        "min_macro_score": min_macro_score,
        "candidates": rows,
        "summary": _summarize(rows),
    }


def run_analysis(
    ctx: AnalysisContext,
    *,
    index_types: List[str],
    min_total_score: float,
    min_technical_score: Optional[float],
    min_macro_score: Optional[float],
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    score_ma: int,
) -> Dict:
    results = [
        analyze_single_index(
            ctx,
            index_type=index_type,
            min_total_score=min_total_score,
            min_technical_score=min_technical_score,
            min_macro_score=min_macro_score,
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            buy_threshold=buy_threshold,
            score_ma=score_ma,
        )
        for index_type in index_types
    ]
    return {
        "min_total_score": min_total_score,
        "min_technical_score": min_technical_score,
        "min_macro_score": min_macro_score,
        "results": results,
    }


def _build_context() -> AnalysisContext:
    market_service = SP500MarketService()
    macro_service = MacroDataService()
    event_service = EventService(manual_events_path=ROOT_DIR / "data" / "us_events.json")
    backtest_service = BacktestService(market_service, macro_service, event_service)
    return AnalysisContext(
        backtest_service=backtest_service,
        market_service=market_service,
        macro_service=macro_service,
        event_service=event_service,
    )


def _write_output(payload: Dict, output_format: str, output_path: Optional[str]):
    if output_format == "json":
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        if output_path:
            Path(output_path).write_text(content, encoding="utf-8")
        else:
            print(content)
        return

    rows: List[Dict] = []
    for result in payload["results"]:
        for candidate in result["candidates"]:
            row = dict(candidate)
            row["sell_reason_flags"] = json.dumps(row.get("sell_reason_flags"), ensure_ascii=False)
            rows.append(row)

    header = list(rows[0].keys()) if rows else [
        "index_type",
        "candidate_threshold",
        "date",
        "close",
        "total_score",
        "technical_score",
        "macro_score",
        "event_adjustment",
        "was_actual_sell",
        "sell_gate_open",
        "sell_reason_flags",
        "post_return_20d_pct",
        "post_return_60d_pct",
        "max_drawdown_next_20d_pct",
        "max_drawdown_next_60d_pct",
    ]
    out = Path(output_path).open("w", encoding="utf-8", newline="") if output_path else sys.stdout
    close_required = bool(output_path)
    try:
        writer = csv.DictWriter(out, fieldnames=header)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    finally:
        if close_required:
            out.close()


def main():
    parser = argparse.ArgumentParser(description="Offline SELL candidate analyzer (threshold-hit days).")
    parser.add_argument("--index", dest="index_types", default=None, help="Comma-separated index types")
    parser.add_argument("--threshold", type=float, default=70.0)
    parser.add_argument("--min-total-score", type=float, default=None)
    parser.add_argument("--min-technical-score", type=float, default=None)
    parser.add_argument("--min-macro-score", type=float, default=None)
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--buy-threshold", type=float, default=40.0)
    parser.add_argument("--score-ma", type=int, default=200)
    parser.add_argument("--output-format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()

    min_total_score = args.min_total_score if args.min_total_score is not None else args.threshold
    ctx = _build_context()
    payload = run_analysis(
        ctx,
        index_types=parse_index_types(args.index_types),
        min_total_score=min_total_score,
        min_technical_score=args.min_technical_score,
        min_macro_score=args.min_macro_score,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        initial_cash=args.initial_cash,
        buy_threshold=args.buy_threshold,
        score_ma=args.score_ma,
    )
    _write_output(payload, args.output_format, args.output)


if __name__ == "__main__":
    main()
