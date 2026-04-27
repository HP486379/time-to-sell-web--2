from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Callable, Dict, List


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

from domain.index_type import normalize_index_type
from services.backtest_service import BacktestService
from services.event_service import EventService
from services.macro_data_service import MacroDataService
from services.sp500_market_service import SP500MarketService


DEFAULT_INDEX_TYPES = [
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "NIFTY50",
    "ALLCOUNTRY",
    "ALLCOUNTRY_JPY",
]
DEFAULT_THRESHOLDS = [70.0, 75.0, 80.0, 85.0]


def parse_thresholds(raw: str | None) -> List[float]:
    if not raw:
        return DEFAULT_THRESHOLDS
    values = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    if not values:
        raise ValueError("thresholds is empty")
    return values


def parse_index_types(raw: str | None) -> List[str]:
    if not raw:
        return DEFAULT_INDEX_TYPES
    values: List[str] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(normalize_index_type(token))
    if not values:
        raise ValueError("index list is empty")
    return values


def _flatten_reasons(events: List[Dict], key: str) -> List[str]:
    reasons = set()
    for event in events:
        raw = event.get(key) if isinstance(event, dict) else None
        if isinstance(raw, list):
            reasons.update(str(item) for item in raw)
        elif raw:
            reasons.add(str(raw))
    return sorted(reasons)


def build_row(index_type: str, sell_threshold: float, result: Dict) -> Dict:
    diagnostics = result.get("diagnostics", {}) if isinstance(result, dict) else {}
    trade_summary = diagnostics.get("trade_summary", {}) if isinstance(diagnostics, dict) else {}
    sell_events = diagnostics.get("sell_events", []) if isinstance(diagnostics, dict) else []
    buy_events = diagnostics.get("buy_events", []) if isinstance(diagnostics, dict) else []

    final_equity = float(result["final_value"])
    hold_equity = float(result["buy_and_hold_final"])
    diff_amount = final_equity - hold_equity
    diff_pct = ((diff_amount / hold_equity) * 100) if hold_equity != 0 else 0.0

    return {
        "index_type": index_type,
        "sell_threshold": sell_threshold,
        "final_equity": round(final_equity, 2),
        "hold_equity": round(hold_equity, 2),
        "diff_amount": round(diff_amount, 2),
        "diff_pct": round(diff_pct, 2),
        "trade_count": int(result.get("trade_count", 0)),
        "sell_count": int(trade_summary.get("sell_count", 0)),
        "buy_count": int(trade_summary.get("buy_count", 0)),
        "sell_dates": [event.get("date") for event in sell_events if isinstance(event, dict) and event.get("date")],
        "buy_dates": [event.get("date") for event in buy_events if isinstance(event, dict) and event.get("date")],
        "sell_reasons": _flatten_reasons(sell_events, "sell_reason"),
        "buy_reasons": _flatten_reasons(buy_events, "buy_reason"),
        "sell_post_return_20d_pct": [
            event.get("post_return_20d_pct")
            for event in sell_events
            if isinstance(event, dict) and event.get("post_return_20d_pct") is not None
        ],
        "buyback_return_pct": [
            event.get("return_until_buyback_pct")
            for event in sell_events
            if isinstance(event, dict) and event.get("return_until_buyback_pct") is not None
        ],
        "max_drawdown": result.get("max_drawdown_pct"),
    }


def run_comparison(
    run_backtest: Callable[[date, date, float, float, float, str, int], Dict],
    *,
    start_date: date,
    end_date: date,
    initial_cash: float,
    buy_threshold: float,
    thresholds: List[float],
    index_types: List[str],
    score_ma: int,
) -> List[Dict]:
    rows: List[Dict] = []
    for index_type in index_types:
        for sell_threshold in thresholds:
            result = run_backtest(
                start_date,
                end_date,
                initial_cash,
                buy_threshold,
                sell_threshold,
                index_type,
                score_ma,
            )
            rows.append(build_row(index_type, sell_threshold, result))
    return rows


def _build_backtest_service() -> BacktestService:
    market_service = SP500MarketService()
    macro_service = MacroDataService()
    event_service = EventService(manual_events_path=ROOT_DIR / "data" / "us_events.json")
    return BacktestService(market_service, macro_service, event_service)


def _output_rows(rows: List[Dict], output_format: str, output_path: str | None):
    if output_format == "json":
        payload = json.dumps(rows, ensure_ascii=False, indent=2)
        if output_path:
            Path(output_path).write_text(payload, encoding="utf-8")
        else:
            print(payload)
        return

    if not rows:
        header = [
            "index_type",
            "sell_threshold",
            "final_equity",
            "hold_equity",
            "diff_amount",
            "diff_pct",
            "trade_count",
            "sell_count",
            "buy_count",
            "sell_dates",
            "buy_dates",
            "sell_reasons",
            "buy_reasons",
            "sell_post_return_20d_pct",
            "buyback_return_pct",
            "max_drawdown",
        ]
    else:
        header = list(rows[0].keys())

    if output_path:
        out = Path(output_path).open("w", encoding="utf-8", newline="")
        close_required = True
    else:
        out = sys.stdout
        close_required = False

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
    parser = argparse.ArgumentParser(description="Compare backtest results by sell_threshold (offline tool).")
    parser.add_argument("--start-date", default="2014-01-01")
    parser.add_argument("--end-date", default=date.today().isoformat())
    parser.add_argument("--initial-cash", type=float, default=1_000_000.0)
    parser.add_argument("--buy-threshold", type=float, default=40.0)
    parser.add_argument("--thresholds", default="70,75,80,85")
    parser.add_argument("--index", dest="index_types", default=None, help="Comma-separated index types")
    parser.add_argument("--score-ma", type=int, default=200)
    parser.add_argument("--output-format", choices=["json", "csv"], default="json")
    parser.add_argument("--output", default=None, help="Output file path. If omitted, print to stdout.")
    args = parser.parse_args()

    thresholds = parse_thresholds(args.thresholds)
    index_types = parse_index_types(args.index_types)

    service = _build_backtest_service()
    rows = run_comparison(
        service.run_backtest,
        start_date=date.fromisoformat(args.start_date),
        end_date=date.fromisoformat(args.end_date),
        initial_cash=args.initial_cash,
        buy_threshold=args.buy_threshold,
        thresholds=thresholds,
        index_types=index_types,
        score_ma=args.score_ma,
    )
    _output_rows(rows, args.output_format, args.output)


if __name__ == "__main__":
    main()
