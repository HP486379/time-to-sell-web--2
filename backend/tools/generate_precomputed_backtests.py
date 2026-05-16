from __future__ import annotations

import json
import os
import sys
import traceback
from dataclasses import dataclass
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

END_DATE = date(2025, 12, 31)
INITIAL_CASH = 1_000_000.0
BUY_THRESHOLD = 40.0
SELL_THRESHOLD = 80.0
SCORE_MA = 200
START_DATE_TOLERANCE_DAYS = int(os.getenv("PRECOMPUTED_START_DATE_TOLERANCE_DAYS", "7"))


@dataclass(frozen=True)
class TargetConfig:
    index_type: str
    start_date: date
    end_date: date = END_DATE
    preset: str = "hybrid"


DEFAULT_TARGETS = [
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "ALLCOUNTRY_JPY",
    "NIFTY50",
]

HYBRID_TARGET_CONFIGS: dict[str, TargetConfig] = {
    # Full 2000-start data is available through the current providers.
    "SP500": TargetConfig("SP500", date(2000, 1, 1), preset="hybrid"),
    "SP500_JPY": TargetConfig("SP500_JPY", date(2000, 1, 1), preset="hybrid"),
    "NIKKEI225": TargetConfig("NIKKEI225", date(2000, 1, 1), preset="hybrid"),
    # Provider-limited earliest usable dates confirmed by generation attempt.
    "TOPIX": TargetConfig("TOPIX", date(2008, 1, 4), preset="hybrid"),
    "ALLCOUNTRY_JPY": TargetConfig("ALLCOUNTRY_JPY", date(2008, 3, 28), preset="hybrid"),
    "NIFTY50": TargetConfig("NIFTY50", date(2007, 9, 17), preset="hybrid"),
}


def _fixed_start_target_configs(start_year: int) -> dict[str, TargetConfig]:
    start = date(start_year, 1, 1)
    preset = f"standard_{start_year}"
    return {
        index_type: TargetConfig(index_type, start, preset=preset)
        for index_type in DEFAULT_TARGETS
    }


PRESET_CONFIGS: dict[str, dict[str, TargetConfig]] = {
    "hybrid": HYBRID_TARGET_CONFIGS,
    "standard_2005": _fixed_start_target_configs(2005),
    "standard_2010": _fixed_start_target_configs(2010),
    "standard_2015": _fixed_start_target_configs(2015),
}

DEFAULT_PRESETS = ["hybrid"]


def _selected_presets() -> list[str]:
    raw = os.getenv("PRECOMPUTED_PRESETS", "").strip()
    if not raw:
        return DEFAULT_PRESETS
    requested = [item.strip().lower() for item in raw.split(",") if item.strip()]
    invalid = [item for item in requested if item not in PRESET_CONFIGS]
    if invalid:
        raise ValueError(f"unknown PRECOMPUTED_PRESETS: {invalid}; allowed={list(PRESET_CONFIGS)}")
    return requested


def _selected_targets() -> list[str]:
    raw = os.getenv("PRECOMPUTED_TARGETS", "").strip()
    if not raw:
        return DEFAULT_TARGETS
    requested = [item.strip().upper() for item in raw.split(",") if item.strip()]
    invalid = [item for item in requested if item not in DEFAULT_TARGETS]
    if invalid:
        raise ValueError(f"unknown PRECOMPUTED_TARGETS: {invalid}; allowed={DEFAULT_TARGETS}")
    return requested


def _selected_configs() -> list[TargetConfig]:
    targets = set(_selected_targets())
    configs: list[TargetConfig] = []
    seen: set[tuple[str, date, date]] = set()
    for preset in _selected_presets():
        for index_type, config in PRESET_CONFIGS[preset].items():
            if index_type not in targets:
                continue
            key = (config.index_type, config.start_date, config.end_date)
            if key in seen:
                continue
            seen.add(key)
            configs.append(config)
    return configs


def _output_filename(config: TargetConfig) -> str:
    return (
        f"{config.index_type.lower()}_{config.start_date.isoformat()}_{config.end_date.isoformat()}_"
        f"sell{int(SELL_THRESHOLD)}_buy{int(BUY_THRESHOLD)}_ma{int(SCORE_MA)}.json"
    )


def _validate_generated_payload(config: TargetConfig, payload: dict) -> None:
    result = payload.get("result") or {}
    price_history = result.get("price_history") or []
    equity_curve = result.get("equity_curve") or result.get("portfolio_history") or []

    if len(price_history) <= 2:
        raise ValueError(
            f"generated precomputed backtest looks like placeholder data: "
            f"index_type={config.index_type}, price_history_points={len(price_history)}"
        )
    if len(equity_curve) <= 2:
        raise ValueError(
            f"generated precomputed backtest has too few equity points: "
            f"index_type={config.index_type}, equity_points={len(equity_curve)}"
        )

    first_date_text = str(price_history[0][0]) if price_history else None
    if first_date_text:
        first_date = date.fromisoformat(first_date_text)
        if first_date < config.start_date:
            raise ValueError(
                f"generated precomputed backtest starts before configured range: "
                f"index_type={config.index_type}, configured_start={config.start_date.isoformat()}, "
                f"first_price_date={first_date.isoformat()}"
            )
        start_lag_days = (first_date - config.start_date).days
        if start_lag_days > START_DATE_TOLERANCE_DAYS:
            raise ValueError(
                f"generated precomputed backtest starts too late: "
                f"index_type={config.index_type}, configured_start={config.start_date.isoformat()}, "
                f"first_price_date={first_date.isoformat()}, lag_days={start_lag_days}, "
                f"tolerance_days={START_DATE_TOLERANCE_DAYS}"
            )
        payload.setdefault("source_policy", {})["first_price_date"] = first_date.isoformat()
        payload.setdefault("source_policy", {})["start_lag_days"] = start_lag_days


def _generate_one(service: BacktestService, config: TargetConfig) -> str:
    result = service.run_backtest(
        config.start_date,
        config.end_date,
        INITIAL_CASH,
        BUY_THRESHOLD,
        SELL_THRESHOLD,
        config.index_type,
        SCORE_MA,
        debug=False,
    )
    payload = {
        "precomputed_key": build_precomputed_backtest_key(
            index_type=config.index_type,
            start_date_iso=config.start_date.isoformat(),
            end_date_iso=config.end_date.isoformat(),
            initial_cash=INITIAL_CASH,
            buy_threshold=BUY_THRESHOLD,
            sell_threshold=SELL_THRESHOLD,
            score_ma=SCORE_MA,
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "logic_version": "v1",
        "git_commit": os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or "unknown",
        "source_policy": {
            "type": "provider_available_start_date",
            "preset": config.preset,
            "configured_start_date": config.start_date.isoformat(),
            "end_date": config.end_date.isoformat(),
            "start_date_tolerance_days": START_DATE_TOLERANCE_DAYS,
        },
        "result": result,
    }
    _validate_generated_payload(config, payload)
    fn = _output_filename(config)
    (OUT_DIR / fn).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return fn


if __name__ == "__main__":
    market = SP500MarketService()
    macro = MacroDataService()
    events = EventService()
    service = BacktestService(market, macro, events)

    successes: list[str] = []
    failures: dict[str, str] = {}

    for config in _selected_configs():
        label = f"{config.preset}:{config.index_type}:{config.start_date.isoformat()}"
        try:
            fn = _generate_one(service, config)
            successes.append(label)
            print(f"wrote {fn}")
        except Exception as exc:
            failures[label] = str(exc)
            print(f"failed {label}: {exc}")
            if os.getenv("PRECOMPUTED_VERBOSE_ERRORS", "").lower() in {"1", "true", "yes", "on"}:
                traceback.print_exc()
            continue

    print("\n=== precomputed generation summary ===")
    print(f"successes: {successes}")
    print(f"failures: {failures}")

    if failures:
        sys.exit(1)
