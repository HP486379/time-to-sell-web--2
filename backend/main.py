from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import List, Optional
import math
import statistics
import logging
from enum import Enum

from fastapi import FastAPI, HTTPException, Query, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

from scoring.technical import calculate_technical_score, calculate_ultra_long_mas
from scoring.macro import calculate_macro_score
from scoring.events import calculate_event_adjustment
from scoring.total_score import calculate_total_score, get_label
from services.sp500_market_service import SP500MarketService
from services.price_history_service import PriceHistoryService, PriceHistoryFetchError
from services.macro_data_service import MacroDataService
from services.event_service import EventService
from services.nav_service import FundNavService
from services.backtest_service import BacktestService
import purchases_store
from domain.index_type import normalize_index_type

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


# ======================
# FastAPI & CORS Config
# ======================

app = FastAPI(title="S&P500 Timing API")

ALLOWED_ORIGINS = [
    "https://time-to-sell-web-2.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://time-to-sell-web-2.vercel.app",
        "http://localhost:5173",
    ],
    allow_origin_regex=r"^https://.*\.vercel\.app$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ======================
# Models & Enums
# ======================

class IndexType(str, Enum):
    SP500 = "SP500"
    SP500_JPY = "SP500_JPY"
    TOPIX = "TOPIX"
    NIKKEI225 = "NIKKEI225"
    NIFTY50 = "NIFTY50"
    ALLCOUNTRY = "ALLCOUNTRY"
    ALLCOUNTRY_JPY = "ALLCOUNTRY_JPY"


def _normalize_index_type_value(value):
    """Normalize legacy index type names to canonical uppercase values."""
    return normalize_index_type(value)


class PositionRequest(BaseModel):
    index_type: IndexType = IndexType.SP500
    total_quantity: int = 0
    avg_cost: float = 0.0
    score_ma: int = Field(200, description="スコア計算に使う移動平均日数")

    @validator("index_type", pre=True)
    def normalize_index_type(cls, value):
        return _normalize_index_type_value(value)


class PricePoint(BaseModel):
    date: str
    close: float
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma200: Optional[float] = None


class Event(BaseModel):
    name: str
    importance: int
    date: str
    source: Optional[str] = None
    description: Optional[str] = None


class IOSVerifyRequest(BaseModel):
    product_id: str
    transaction_id: str


class PurchaseRequest(BaseModel):
    user_id: str
    product_id: str
    transaction_id: str


class BacktestRequest(BaseModel):
    index_type: IndexType = IndexType.SP500
    start_date: date
    end_date: date
    initial_cash: float
    buy_threshold: float = 40.0
    sell_threshold: float = 80.0
    score_ma: int = Field(200)

    @validator("index_type", pre=True)
    def normalize_index_type(cls, value):
        return _normalize_index_type_value(value)


class BacktestSummary(BaseModel):
    final_equity: float
    hold_equity: float
    total_return: float
    max_drawdown: float
    trade_count: int


class BacktestPoint(BaseModel):
    date: date
    close: float
    ma20: Optional[float] = None
    ma60: Optional[float] = None
    ma200: Optional[float] = None


class BacktestResponse(BaseModel):
    summary: BacktestSummary
    equity_curve: List[BacktestPoint]


# ======================
# Services
# ======================

MANUAL_EVENTS_PATH = Path(__file__).parent / "data" / "us_events.json"

market_service = SP500MarketService()
price_history_service = PriceHistoryService(market_service, ttl=timedelta(minutes=15))
macro_service = MacroDataService()
event_service = EventService(manual_events_path=MANUAL_EVENTS_PATH)
nav_service = FundNavService()
backtest_service = BacktestService(market_service, macro_service, event_service)
purchases_store.init_db()

JST = timezone(timedelta(hours=9))


def to_jst_iso(value: date) -> str:
    return datetime.combine(value, time.min, tzinfo=JST).isoformat()


def _serialize_event(event: dict) -> dict:
    serialized = dict(event)
    event_date = serialized.get("date")
    if isinstance(event_date, date):
        serialized["date"] = event_date.isoformat()
    return serialized


def _serialize_event_details(details: dict) -> dict:
    if not details:
        return details
    serialized = dict(details)
    effective_event = serialized.get("effective_event")
    if isinstance(effective_event, dict):
        serialized["effective_event"] = _serialize_event(effective_event)
    events = serialized.get("events")
    if isinstance(events, list):
        serialized["events"] = [
            _serialize_event(event) for event in events if isinstance(event, dict)
        ]
    return serialized


# ======================
# Cache
# ======================

_cache_ttl = timedelta(seconds=60)
_cached_snapshot = {}
_cached_at: dict[str, datetime] = {}
MIN_PRICE_POINTS = 200


# ======================
# Helpers
# ======================

def _price_history_range():
    today = date.today()
    return today - timedelta(days=365 * 5), today


def _get_price_series(index_type: IndexType):
    price_history = market_service.get_price_history(index_type.value, allow_synthetic=False)
    source = market_service.get_last_source(index_type.value)
    restricted = {IndexType.NIFTY50, IndexType.ALLCOUNTRY, IndexType.ALLCOUNTRY_JPY}
    allowed_sources = {"nav_api", "stooq", "yfinance", "last_good", "bootstrap", "real", "real_fallback"}
    if index_type in restricted and source not in allowed_sources:
        raise PriceHistoryFetchError(f"price history unavailable for chart source={source}")
    return market_service.build_price_series_with_ma(price_history)


def _get_price_series_or_503(index_type: IndexType):
    try:
        return _get_price_series(index_type)
    except (PriceHistoryFetchError, ValueError):
        raise HTTPException(status_code=503, detail="Price data unavailable.")
    except Exception as exc:
        logger.warning("price-history failed index=%s error=%s", index_type.value, exc, exc_info=True)
        raise HTTPException(status_code=503, detail="Price data unavailable.")


def _is_debug_eligible_for_scoring(index_type: IndexType, price_history: List[Tuple[str, float]]) -> tuple[bool, str]:
    debug = market_service.get_last_debug(index_type.value)
    source = str(debug.get("source") or market_service.get_last_source(index_type.value) or "")
    adopted_provider = str(debug.get("adopted_provider") or "")
    disallowed_sources = {"synthetic", "synthetic_fallback", "bootstrap", "fallback_degraded", "real_fallback", "last_good"}
    if adopted_provider == "synthetic_fallback":
        return False, "synthetic_fallback_scoring_disabled"
    if source in disallowed_sources or "degraded" in source:
        return False, f"source_scoring_disabled:{source}"
    if not (source == "real" or adopted_provider == "yfinance"):
        return False, f"scoring_source_not_allowed:source={source},provider={adopted_provider}"
    if not price_history:
        return False, "series_empty"
    values = [float(v) for _, v in price_history]
    nan_count = sum(1 for v in values if math.isnan(v))
    if nan_count >= max(3, len(values) // 2):
        return False, f"series_nan_heavy:{nan_count}/{len(values)}"
    cleaned = [v for v in values if not math.isnan(v)]
    if not cleaned:
        return False, "series_all_nan"
    simple_anomaly_reason = market_service.simple_anomaly_reason(price_history, index_type.value)
    if simple_anomaly_reason:
        return False, f"series_simple_anomaly:{simple_anomaly_reason}"
    if any(v <= 0 for v in cleaned[-5:]):
        return False, "series_non_positive_tail"
    if len(cleaned) >= 3:
        tail = cleaned[-5:]
        ratios = [tail[i] / tail[i - 1] for i in range(1, len(tail)) if tail[i - 1] > 0]
        if any(r < 0.2 or r > 1.8 for r in ratios):
            return False, "series_tail_broken"
    if index_type == IndexType.TOPIX and len(cleaned) >= 40:
        min_v, max_v = min(cleaned), max(cleaned)
        if min_v <= 0:
            return False, "topix_non_positive"
        if (max_v / min_v) > 8.0:
            return False, "topix_max_min_ratio_abnormal"
        head = cleaned[:20]
        tail = cleaned[-20:]
        head_med = statistics.median(head)
        tail_med = statistics.median(tail)
        if head_med > 0 and (tail_med / head_med < 0.2 or tail_med / head_med > 5.0):
            return False, "topix_head_tail_scale_gap"
        recent = cleaned[-5:]
        base_med = statistics.median(cleaned[-25:-5]) if len(cleaned) >= 25 else statistics.median(cleaned[:-5])
        if base_med > 0:
            recent_med = statistics.median(recent)
            if recent_med / base_med < 0.5 or recent_med / base_med > 1.8:
                return False, "topix_recent_scale_switch"
    return True, "series_ok"


def _build_event_adjustment(target: date):
    events = event_service.get_events_for_date(target)
    diag = event_service.get_diagnostics()
    logger.info(
        "[events-pipeline] target=%s returned_events=%d before_filter=%s after_filter=%s file=%s",
        target,
        len(events) if isinstance(events, list) else -1,
        diag.get("events_before_filter"),
        diag.get("events_after_filter"),
        diag.get("events_file_path"),
    )
    try:
        result = calculate_event_adjustment(target, events)
    except TypeError:
        # 旧シグネチャ互換
        result = calculate_event_adjustment(events)

    if isinstance(result, tuple):
        if len(result) == 3:
            event_adjustment, event_details, event_count = result
        elif len(result) == 2:
            event_adjustment, event_details = result
            event_count = len(events) if isinstance(events, list) else 0
        else:
            event_adjustment, event_details, event_count = 0.0, {}, 0
    else:
        event_adjustment, event_details, event_count = 0.0, {}, 0

    event_details = _serialize_event_details(event_details if isinstance(event_details, dict) else {})
    logger.info(
        "[events-adjustment] input_events=%d event_count=%d adjustment=%s details=%s",
        len(events) if isinstance(events, list) else -1,
        int(event_count or 0),
        float(event_adjustment or 0.0),
        event_details,
    )
    return float(event_adjustment or 0.0), event_details, int(event_count or 0)


def get_cached_snapshot(
    index_type: IndexType,
    allow_synthetic: bool = False,
    allow_low_quality: bool = False,
) -> dict:
    key = f"{index_type.value}|synth={int(allow_synthetic)}|lowq={int(allow_low_quality)}"
    now = datetime.now(timezone.utc)
    if key in _cached_at and (now - _cached_at[key]) < _cache_ttl:
        return _cached_snapshot[key]

    snapshot = {
        "current_price": 0.0,
        "scores": {
            "technical": None,
            "macro": None,
            "event_adjustment": None,
            "total": None,
            "label": "N/A",
        },
        "technical_details": {},
        "macro_details": {},
        "event_details": {},
        "event_count": 0,
        "price_history": [],
        "price_series": [],
        "source": "real",
        "adopted_provider": None,
    }

    try:
        price_history = market_service.get_price_history(
            index_type.value,
            allow_synthetic=allow_synthetic,
            allow_low_quality=allow_low_quality,
        )
    except PriceHistoryFetchError:
        logger.exception("[snapshot] price history unavailable for %s", index_type.value)
        snapshot["source"] = "data_unavailable"
        snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
        snapshot["status"] = "error"
        snapshot["reasons"] = ["PRICE_HISTORY_UNAVAILABLE"]
        return snapshot
    except Exception:
        logger.exception("[snapshot] price history failed for %s", index_type.value)
        snapshot["source"] = "data_unavailable"
        snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
        snapshot["status"] = "error"
        snapshot["reasons"] = ["PRICE_HISTORY_UNAVAILABLE"]
        return snapshot

    if not price_history:
        logger.warning("[snapshot] empty price history for %s", index_type.value)
        snapshot["source"] = "data_unavailable"
        snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
        snapshot["status"] = "error"
        snapshot["reasons"] = ["PRICE_HISTORY_EMPTY"]
        return snapshot

    current_price = price_history[-1][1]
    market_service._set_debug(
        index_type.value,
        scoring_input_series_head=price_history[:5],
        scoring_input_series_tail=price_history[-10:],
        scoring_input_series_points=len(price_history),
    )
    snapshot["source"] = market_service.get_last_source(index_type.value)
    snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
    restricted = {IndexType.NIFTY50, IndexType.ALLCOUNTRY, IndexType.ALLCOUNTRY_JPY}
    allowed_sources = {"nav_api", "stooq", "yfinance", "last_good", "bootstrap", "real", "real_fallback"}
    if allow_low_quality:
        allowed_sources = set(allowed_sources) | {"fallback_degraded", "synthetic"}
    if index_type in restricted and snapshot["source"] not in allowed_sources:
        logger.warning(
            "[snapshot] disallow non-real source for %s source=%s",
            index_type.value,
            snapshot["source"],
        )
        snapshot["source"] = "data_unavailable"
        snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
        snapshot["status"] = "error"
        snapshot["reasons"] = ["SOURCE_DISALLOWED"]
        return snapshot

    eligible, reason = _is_debug_eligible_for_scoring(index_type, price_history)
    if not eligible:
        logger.warning("[snapshot] scoring blocked index=%s reason=%s", index_type.value, reason)
        snapshot["adopted_provider"] = market_service.get_last_debug(index_type.value).get("adopted_provider")
        market_service._set_debug(index_type.value, scoring_allowed=False, scoring_executed=False, scoring_block_reason=reason)
        snapshot["debug"] = market_service.get_last_debug(index_type.value)
        snapshot["status"] = "degraded"
        snapshot["reasons"] = [reason]
        return snapshot
    market_service._set_debug(index_type.value, scoring_allowed=True, scoring_executed=True, scoring_block_reason=None)

    try:
        technical_score, technical_details = calculate_technical_score(price_history)
    except Exception:
        logger.exception("[snapshot] technical calc failed for %s", index_type.value)
        technical_score, technical_details = 0.0, {}

    try:
        macro_data = macro_service.get_macro_series()
        macro_score, macro_details = calculate_macro_score(
            macro_data["r_10y"], macro_data["cpi"], macro_data["vix"]
        )
    except Exception:
        logger.exception("[snapshot] macro calc failed for %s", index_type.value)
        macro_score, macro_details = 0.0, {}

    try:
        target = date.fromisoformat(price_history[-1][0])
        event_adjustment, event_details, event_count = _build_event_adjustment(target)
    except Exception:
        logger.exception("[snapshot] events calc failed for %s", index_type.value)
        event_adjustment, event_details, event_count = 0.0, {}, 0

    ma500, ma1000 = calculate_ultra_long_mas(price_history)

    period_windows = {"short": 20, "mid": 60, "long": 200}
    period_scores = {"short": 0.0, "mid": 0.0, "long": 0.0}
    period_breakdowns = {}

    for key_name, window in period_windows.items():
        try:
            period_technical_score, period_technical_details = calculate_technical_score(
                price_history, base_window=window
            )
        except Exception:
            logger.exception(
                "[snapshot] period technical calc failed for %s (%s)",
                index_type.value,
                key_name,
            )
            period_technical_score, period_technical_details = 0.0, {}

        period_total = round(
            calculate_total_score(
                period_technical_score,
                macro_score,
                0.0,
                current_price=current_price,
                ma500=ma500,
                ma1000=ma1000,
            ),
            2,
        )
        period_scores[key_name] = period_total
        period_breakdowns[key_name] = {
            "scores": {
                "technical": period_technical_score,
                "macro": macro_score,
                "event_adjustment": event_adjustment,
                "total": period_total,
            },
            "technical_details": period_technical_details,
            "macro_details": macro_details,
        }

    base_score = (
        period_scores["short"] * 0.2
        + period_scores["mid"] * 0.3
        + period_scores["long"] * 0.5
    )
    if (
        period_scores["short"] >= 80
        and period_scores["mid"] >= 80
        and period_scores["long"] >= 80
    ):
        bonus = 10
    elif (
        period_scores["short"] >= 70
        and period_scores["mid"] >= 70
        and period_scores["long"] >= 70
    ):
        bonus = 6
    elif period_scores["mid"] >= 70 and period_scores["long"] >= 70:
        bonus = 3
    elif period_scores["short"] >= 70 and period_scores["mid"] >= 70:
        bonus = 2
    else:
        bonus = 0

    total_score = round(
        max(0.0, min(100.0, base_score + bonus + event_adjustment)),
        2,
    )
    label = get_label(total_score)

    snapshot.update(
        {
            "current_price": current_price,
            "scores": {
                "technical": technical_score,
                "macro": macro_score,
                "event_adjustment": event_adjustment,
                "total": total_score,
                "label": label,
                "period_total": period_scores["long"],
                "bonus": bonus,
            },
            "period_scores": period_scores,
            "period_meta": {
                "short_window": period_windows["short"],
                "mid_window": period_windows["mid"],
                "long_window": period_windows["long"],
            },
            "period_breakdowns": period_breakdowns,
            "technical_details": technical_details,
            "macro_details": macro_details,
            "event_details": event_details,
            "event_count": event_count,
            "price_history": price_history,
            "price_series": market_service.build_price_series_with_ma(price_history),
        }
    )
    market_service._set_debug(index_type.value, scores_total=total_score)
    _cached_snapshot[key] = snapshot
    _cached_at[key] = now
    return snapshot


def _build_debug_payload(requested_index_type: str, used_index_type: str, snapshot: dict) -> dict:
    service_debug = market_service.get_last_debug(used_index_type)
    price_history = snapshot.get("price_history") or []
    technical_score = float((snapshot.get("scores") or {}).get("technical", 0.0) or 0.0)
    period_scores = snapshot.get("period_scores") or {}
    return {
        "requested_index_type": requested_index_type,
        "used_index_type": used_index_type,
        "source": snapshot.get("source"),
        "status": snapshot.get("status"),
        "source_confidence": service_debug.get("source_confidence"),
        "symbol": service_debug.get("symbol"),
        "resolved_symbol": service_debug.get("resolved_symbol"),
        "provider_path": service_debug.get("provider_path"),
        "selected_function": service_debug.get("selected_function"),
        "price_column_used": service_debug.get("price_column_used"),
        "raw_columns": service_debug.get("raw_columns"),
        "raw_shape": service_debug.get("raw_shape"),
        "raw_is_multiindex": service_debug.get("raw_is_multiindex"),
        "raw_head": service_debug.get("raw_head"),
        "raw_tail": service_debug.get("raw_tail"),
        "raw_close_tail": service_debug.get("raw_close_tail"),
        "raw_close_head": service_debug.get("raw_close_head"),
        "raw_adj_close_tail": service_debug.get("raw_adj_close_tail"),
        "raw_adj_close_head": service_debug.get("raw_adj_close_head"),
        "normalized_series_head": service_debug.get("normalized_series_head"),
        "normalized_series_tail": service_debug.get("normalized_series_tail"),
        "series_sort_order": service_debug.get("series_sort_order"),
        "fx_symbol": service_debug.get("fx_symbol"),
        "price_type": service_debug.get("price_type"),
        "fetch_error": service_debug.get("fetch_error"),
        "fetch_error_repr": service_debug.get("fetch_error_repr"),
        "fetch_error_trace": service_debug.get("fetch_error_trace"),
        "validation_reason": service_debug.get("validation_reason"),
        "quality_flags": service_debug.get("quality_flags"),
        "quality_summary": service_debug.get("quality_summary"),
        "tried_providers": service_debug.get("tried_providers"),
        "adopted_provider": service_debug.get("adopted_provider"),
        "provider_reject_reasons": service_debug.get("provider_reject_reasons"),
        "quality_check": service_debug.get("quality_check"),
        "price_history_points": service_debug.get("points", len(price_history)),
        "combined_points": service_debug.get("combined_points"),
        "first_close": service_debug.get("first_close"),
        "last_close": service_debug.get("last_close"),
        "one_year_return": service_debug.get("one_year_return"),
        "price_stats_source": service_debug.get("price_stats_source"),
        "adoption_reason": service_debug.get("adoption_reason"),
        "topix_alt_probe": service_debug.get("topix_alt_probe"),
        "event_count": snapshot.get("event_count"),
        "event_adjustment": (snapshot.get("scores") or {}).get("event_adjustment"),
        "events_file_path": event_service.get_diagnostics().get("events_file_path"),
        "raw_events_count": event_service.get_diagnostics().get("raw_events_count"),
        "parsed_events_count": event_service.get_diagnostics().get("parsed_events_count"),
        "parse_failed_count": event_service.get_diagnostics().get("parse_failed_count"),
        "event_filter_range": {
            "today": event_service.get_diagnostics().get("today"),
            "window_start": event_service.get_diagnostics().get("window_start"),
            "window_end": event_service.get_diagnostics().get("window_end"),
            "timezone": event_service.get_diagnostics().get("timezone"),
            "events_before_filter": event_service.get_diagnostics().get("events_before_filter"),
            "events_after_filter": event_service.get_diagnostics().get("events_after_filter"),
        },
        "filtered_events_count": event_service.get_diagnostics().get("events_after_filter"),
        "sample_events": event_service.get_diagnostics().get("sample_events"),
        "scores_total": (snapshot.get("scores") or {}).get("total"),
        "scoring_executed": service_debug.get("scoring_executed"),
        "technical_score": technical_score,
        "period_scores": {
            "short": period_scores.get("short"),
            "mid": period_scores.get("mid"),
            "long": period_scores.get("long"),
        },
        "reasons": (snapshot.get("technical_details") or {}).get("reason"),
        "snapshot_reasons": snapshot.get("reasons"),
    }


def _truthy(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value == 1
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


async def _resolve_debug_flag(request: Request, query_debug: bool) -> bool:
    query_raw = request.query_params.get("debug")
    body_raw = None
    try:
        payload = await request.json()
        if isinstance(payload, dict):
            body_raw = payload.get("debug")
    except Exception:
        body_raw = None
    resolved = _truthy(query_debug) or _truthy(query_raw) or _truthy(body_raw)
    logger.info("[evaluate] debug_resolved=%s query=%s body=%s", resolved, query_raw, body_raw)
    return resolved


# ======================
# NAV Endpoints
# ======================

@app.get("/api/nav/sp500-synthetic")
def get_synthetic_nav():
    return nav_service.get_synthetic_nav()


@app.get("/api/nav/emaxis-slim-sp500")
def get_fund_nav():
    nav = nav_service.get_official_nav()
    if nav:
        return nav
    synthetic = nav_service.get_synthetic_nav()
    return {
        "asOf": synthetic["asOf"],
        "navJpy": synthetic["navJpy"],
        "source": "synthetic",
    }


# ======================
# Price History Endpoints
# ======================

@app.get("/api/sp500/price-history", response_model=List[PricePoint])
def get_sp500_history():
    return _get_price_series_or_503(IndexType.SP500)


@app.get("/api/sp500-jpy/price-history", response_model=List[PricePoint])
def get_sp500_jpy_history():
    return _get_price_series_or_503(IndexType.SP500_JPY)


@app.get("/api/topix/price-history", response_model=List[PricePoint])
def get_topix_history():
    return _get_price_series_or_503(IndexType.TOPIX)


@app.get("/api/nikkei/price-history", response_model=List[PricePoint])
def get_nikkei_history():
    return _get_price_series_or_503(IndexType.NIKKEI225)


@app.get("/api/nifty50/price-history", response_model=List[PricePoint])
def get_nifty_history():
    return _get_price_series_or_503(IndexType.NIFTY50)


@app.get("/api/orukan/price-history", response_model=List[PricePoint])
def get_orukan_history():
    return _get_price_series_or_503(IndexType.ALLCOUNTRY)


@app.get("/api/orukan-jpy/price-history", response_model=List[PricePoint])
def get_orukan_jpy_history():
    return _get_price_series_or_503(IndexType.ALLCOUNTRY_JPY)


# ======================
# Backtest Endpoints
# ======================

def _build_equity_curve(price_history: List[tuple]) -> List[BacktestPoint]:
    closes = [close for _, close in price_history]

    def moving_average(values: List[float], window: int) -> List[Optional[float]]:
        averaged: List[Optional[float]] = []
        for idx in range(len(values)):
            if idx + 1 < window:
                averaged.append(None)
                continue
            window_values = values[idx + 1 - window : idx + 1]
            averaged.append(round(sum(window_values) / window, 2))
        return averaged

    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma200 = moving_average(closes, 200)

    return [
        BacktestPoint(
            date=date.fromisoformat(date_str),
            close=close,
            ma20=ma20[idx],
            ma60=ma60[idx],
            ma200=ma200[idx],
        )
        for idx, (date_str, close) in enumerate(price_history)
    ]


@app.post("/api/backtest", response_model=BacktestResponse)
def run_backtest(payload: BacktestRequest):
    try:
        result = backtest_service.run_backtest(
            payload.start_date,
            payload.end_date,
            payload.initial_cash,
            payload.buy_threshold,
            payload.sell_threshold,
            payload.index_type.value,
            payload.score_ma,
        )
        price_history = result.get("price_history", [])
        equity_curve = _build_equity_curve(price_history)
        summary = BacktestSummary(
            final_equity=result["final_value"],
            hold_equity=result["buy_and_hold_final"],
            total_return=result["total_return_pct"],
            max_drawdown=result["max_drawdown_pct"],
            trade_count=result["trade_count"],
        )
        return BacktestResponse(summary=summary, equity_curve=equity_curve)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception:
        logger.exception("Backtest failed", exc_info=True)
        raise HTTPException(
            status_code=502,
            detail="Backtest failed: external data unavailable.",
        )


# ======================
# Evaluate Endpoints
# ======================

@app.post("/api/sp500/evaluate")
async def evaluate_sp500(
    request: Request,
    position: PositionRequest,
    debug: bool = Query(False),
    allow_low_quality: bool = Query(False),
):
    try:
        debug_flag = await _resolve_debug_flag(request, debug)
        requested_index_type = str(position.index_type.value)
        used_index_type = normalize_index_type(requested_index_type)
        snapshot = get_cached_snapshot(
            position.index_type,
            allow_synthetic=debug_flag,
            allow_low_quality=allow_low_quality,
        )
        debug_payload = _build_debug_payload(requested_index_type, used_index_type, snapshot)
        logger.info("[evaluate] debug=%s", debug_payload)
        if used_index_type == "TOPIX":
            logger.info(
                "[topix-runtime] requested_index_type=%s resolved_symbol=%s provider_path=%s selected_function=%s "
                "price_column_used=%s first_close=%s last_close=%s one_year_return=%s scoring_executed=%s "
                "adopted_provider=%s adoption_reason=%s",
                debug_payload.get("requested_index_type"),
                debug_payload.get("resolved_symbol"),
                debug_payload.get("provider_path"),
                debug_payload.get("selected_function"),
                debug_payload.get("price_column_used"),
                debug_payload.get("first_close"),
                debug_payload.get("last_close"),
                debug_payload.get("one_year_return"),
                debug_payload.get("scoring_executed"),
                debug_payload.get("adopted_provider"),
                debug_payload.get("adoption_reason"),
            )
        if debug_flag:
            response = dict(snapshot)
            response["source"] = debug_payload.get("source", response.get("source"))
            response["adopted_provider"] = debug_payload.get("adopted_provider", response.get("adopted_provider"))
            if debug_payload.get("provider_reject_reasons"):
                response["provider_reject_reasons"] = debug_payload.get("provider_reject_reasons")
            response["debug"] = debug_payload
            return response
        return snapshot
    except Exception:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=502, detail="Evaluation failed")


@app.post("/api/evaluate")
async def evaluate(
    request: Request,
    position: PositionRequest,
    debug: bool = Query(False),
    allow_low_quality: bool = Query(False),
):
    try:
        debug_flag = await _resolve_debug_flag(request, debug)
        requested_index_type = str(position.index_type.value)
        used_index_type = normalize_index_type(requested_index_type)
        snapshot = get_cached_snapshot(
            position.index_type,
            allow_synthetic=debug_flag,
            allow_low_quality=allow_low_quality,
        )
        debug_payload = _build_debug_payload(requested_index_type, used_index_type, snapshot)
        logger.info("[evaluate] debug=%s", debug_payload)
        if used_index_type == "TOPIX":
            logger.info(
                "[topix-runtime] requested_index_type=%s resolved_symbol=%s provider_path=%s selected_function=%s "
                "price_column_used=%s first_close=%s last_close=%s one_year_return=%s scoring_executed=%s "
                "adopted_provider=%s adoption_reason=%s",
                debug_payload.get("requested_index_type"),
                debug_payload.get("resolved_symbol"),
                debug_payload.get("provider_path"),
                debug_payload.get("selected_function"),
                debug_payload.get("price_column_used"),
                debug_payload.get("first_close"),
                debug_payload.get("last_close"),
                debug_payload.get("one_year_return"),
                debug_payload.get("scoring_executed"),
                debug_payload.get("adopted_provider"),
                debug_payload.get("adoption_reason"),
            )
        if debug_flag:
            response = dict(snapshot)
            response["source"] = debug_payload.get("source", response.get("source"))
            response["adopted_provider"] = debug_payload.get("adopted_provider", response.get("adopted_provider"))
            if debug_payload.get("provider_reject_reasons"):
                response["provider_reject_reasons"] = debug_payload.get("provider_reject_reasons")
            response["debug"] = debug_payload
            return response
        return snapshot
    except Exception:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=502, detail="Evaluation failed")


# ======================
# Purchase Endpoint
# ======================

@app.post("/api/purchase")
def create_purchase(
    payload: PurchaseRequest,
    x_user_id: Optional[str] = Header(None),
):
    """
    iOSアプリからの課金登録エンドポイント。
    X-User-Id ヘッダが存在する場合はそちらを優先し、
    なければ payload.user_id を使用する（冪等性あり）。
    """
    user_id = x_user_id if x_user_id else payload.user_id

    if payload.product_id not in purchases_store.PRODUCT_TO_INDEX:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown product_id: {payload.product_id}. "
                f"Valid values: {list(purchases_store.PRODUCT_TO_INDEX.keys())}"
            ),
        )

    try:
        created = purchases_store.add_purchase(
            user_id=user_id,
            product_id=payload.product_id,
            transaction_id=payload.transaction_id,
        )
        logger.info(
            "[purchase] user_id=%s product_id=%s transaction_id=%s created=%s",
            user_id,
            payload.product_id,
            payload.transaction_id,
            created,
        )
        return {"ok": True, "success": True, "created": created}
    except Exception:
        logger.exception(
            "[purchase] failed user_id=%s product_id=%s transaction_id=%s",
            user_id,
            payload.product_id,
            payload.transaction_id,
        )
        raise HTTPException(status_code=500, detail="Purchase registration failed.")


# =========================
# Events API（デバッグ用）
# =========================

from datetime import date as dt_date  # date型と引数名の衝突回避

@app.get("/api/events")
def get_events_api(date: Optional[str] = Query(None), date_str: Optional[str] = Query(None)):
    """
    デバッグ用イベント取得API

    - /api/events?date=2026-01-02
    - /api/events?date_str=2026-01-02
    - /api/events   ← 今日基準
    """
    try:
        requested_date: Optional[str] = None
        for candidate in (date, date_str):
            if isinstance(candidate, str) and candidate:
                requested_date = candidate
                break

        target = (
            datetime.strptime(requested_date, "%Y-%m-%d").date()
            if requested_date
            else dt_date.today()
        )

        events = event_service.get_events_for_date(target)

        for e in events:
            d = e.get("date")
            if isinstance(d, dt_date):
                e["date"] = d.isoformat()

        return {
            "events": events,
            "target": target.isoformat(),
            "manual_count": len(getattr(event_service, "manual_events", [])),
        }
    except Exception as e:
        return {"error": str(e)}


# ======================
# Debug Endpoints
# ======================

@app.get("/debug/purchases")
def debug_purchases(limit: int = Query(50, ge=1, le=500)):
    """直近の purchases レコードを返す（デバッグ用）。"""
    try:
        rows = purchases_store.get_recent_purchases(limit=limit)
        return {"count": len(rows), "purchases": rows}
    except Exception:
        logger.exception("[debug/purchases] failed")
        raise HTTPException(status_code=500, detail="Failed to fetch purchases.")


@app.get("/api/health")
def health():
    return {"ok": True}


# ======================
# Standalone Run
# ======================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
