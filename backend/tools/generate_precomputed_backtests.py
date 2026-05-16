from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.sp500_market_service import SP500MarketService
from services.macro_data_service import MacroDataService
from services.event_service import EventService
from services.backtest_service import BacktestService
from services.precomputed_key import build_precomputed_backtest_key

OUT_DIR = BACKEND_DIR / "data" / "precomputed_backtests"
OUT_DIR.mkdir(parents=True, exist_ok=True)

START_DATE = date(2000, 1, 1)
END_DATE = date(2025, 12, 31)
INITIAL_CASH = 1_000_000.0
BUY_THRESHOLD = 40.0
SELL_THRESHOLD = 80.0
SCORE_MA = 200

DEFAULT_TARGETS = [
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "ALLCOUNTRY_JPY",
    "NIFTY50",
]


def _selected_targets() -> list[str]:
    raw = os.getenv("PRECOMPUTED_TARGETS", "").strip()
    if not raw:
        return DEFAULT_TARGETS
    requested = [item.strip().upper() for item in raw.split(",") if item.strip()]
    invalid = [item for item in requested if item not in DEFAULT_TARGETS]
    if invalid:
        raise ValueError(f"unknown PRECOMPUTED_TARGETS: {invalid}; allowed={DEFAULT_TARGETS}")
    return requested


def _output_filename(index_type: str) -> str:
    return (
        f"{index_type.lower()}_{START_DATE.isoformat()}_{END_DATE.isoformat()}_"
        f"sell{int(SELL_THRESHOLD)}_buy{int(BUY_THRESHOLD)}_ma{int(SCORE_MA)}.json"
    )


def _validate_generated_payload(index_type: str, payload: dict) -> None:
    result = payload.get("result") or {}
    price_history = result.get("price_history") or []
    equity_curve = result.get("equity_curve") or result.get("portfolio_history") or []

    if len(price_history) <= 2:
        raise ValueError(
            f"generated precomputed backtest looks like placeholder data: "
            f"index_type={index_type}, price_history_points={len(price_history)}"
        )
    if len(equity_curve) <= 2:
        raise ValueError(
            f"generated precomputed backtest has too few equity points: "
            f"index_type={index_type}, equity_points={len(equity_curve)}"
        )


def _generate_one(service: BacktestService, index_type: str) -> str:
    result = service.run_backtest(
        START_DATE,
        END_DATE,
        INITIAL_CASH,
        BUY_THRESHOLD,
        SELL_THRESHOLD,
        index_type,
        SCORE_MA,
        debug=False,
    )
    payload = {
        "precomputed_key": build_precomputed_backtest_key(
            index_type=index_type,
            start_date_iso=START_DATE.isoformat(),
            end_date_iso=END_DATE.isoformat(),
            initial_cash=INITIAL_CASH,
            buy_threshold=BUY_THRESHOLD,
            sell_threshold=SELL_THRESHOLD,
            score_ma=SCORE_MA,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "logic_version": "v1",
        "git_commit": os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or "unknown",
        "result": result,
    }
    _validate_generated_payload(index_type, payload)
    fn = _output_filename(index_type)
    (OUT_DIR / fn).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return fn


if __name__ == "__main__":
    market = SP500MarketService()
    macro = MacroDataService()
    events = EventService()
    service = BacktestService(market, macro, events)

    successes: list[str] = []
    failures: dict[str, str] = {}

    for index_type in _selected_targets():
        try:
            fn = _generate_one(service, index_type)
            successes.append(index_type)
            print(f"wrote {fn}")
        except Exception as exc:
            failures[index_type] = str(exc)
            print(f"failed {index_type}: {exc}")
            if os.getenv("PRECOMPUTED_VERBOSE_ERRORS", "").lower() in {"1", "true", "yes", "on"}:
                traceback.print_exc()
            continue

    print("\n=== precomputed generation summary ===")
    print(f"successes: {successes}")
    print(f"failures: {failures}")

    if failures:
        sys.exit(1)
