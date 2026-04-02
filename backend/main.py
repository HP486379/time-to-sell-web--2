from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import List, Optional
import logging
from enum import Enum

from fastapi import FastAPI, HTTPException, Query, Header
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
    if isinstance(value, str):
        v = value.lower().strip()
        if v in {"nikkei", "nikkei225", "nikkei_225", "nikkei-225"}:
            return "NIKKEI225"
        if v in {"orukan", "allcountry"}:
            return "ALLCOUNTRY"
        if v in {"orukan_jpy", "allcountry_jpy"}:
            return "ALLCOUNTRY_JPY"
        if v == "sp500_jpy":
            return "SP500_JPY"
        if v == "topix":
            return "TOPIX"
        if v == "nifty50":
            return "NIFTY50"
        if v == "sp500":
            return "SP500"
    raise ValueError(f"Invalid index_type: {value}")


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
    price_history = market_service.get_price_history(index_type.value)
    return market_service.build_price_series_with_ma(price_history)


def _get_price_series_or_503(index_type: IndexType):
    try:
        return _get_price_series(index_type)
    except PriceHistoryFetchError:
        raise HTTPException(status_code=503, detail="Price data unavailable.")


def _build_event_adjustment(target: date):
    events = event_service.get_events_for_date(target)
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
    return float(event_adjustment or 0.0), event_details, int(event_count or 0)


def get_cached_snapshot(index_type: IndexType) -> dict:
    key = index_type.value
    now = datetime.now(timezone.utc)
    if key in _cached_at and (now - _cached_at[key]) < _cache_ttl:
        return _cached_snapshot[key]

    snapshot = {
        "current_price": 0.0,
        "scores": {
            "technical": 0.0,
            "macro": 0.0,
            "event_adjustment": 0.0,
            "total": 0.0,
            "label": get_label(0.0),
        },
        "technical_details": {},
        "macro_details": {},
        "event_details": {},
        "event_count": 0,
        "price_history": [],
        "price_series": [],
    }

    try:
        price_history = market_service.get_price_history(index_type.value)
    except PriceHistoryFetchError:
        logger.exception("[snapshot] price history unavailable for %s", index_type.value)
        raise

    if not price_history:
        logger.warning("[snapshot] empty price history for %s", index_type.value)
        return snapshot

    current_price = price_history[-1][1]

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
    period_technical_scores = {"long": technical_score}

    for period_key, window in period_windows.items():
        if period_key == "long":
            continue
        try:
            period_score, _ = calculate_technical_score(price_history, base_window=window)
            period_technical_scores[period_key] = period_score
        except Exception:
            logger.exception(
                "[snapshot] period technical calc failed for %s (window=%s)",
                index_type.value,
                window,
            )
            period_technical_scores[period_key] = technical_score

    period_scores = {
        key: round(
            calculate_total_score(
                period_technical_scores[key],
                macro_score,
                event_adjustment,
                current_price=current_price,
                ma500=ma500,
                ma1000=ma1000,
            ),
            2,
        )
        for key in period_windows.keys()
    }

    total_score = calculate_total_score(
        technical_score,
        macro_score,
        event_adjustment,
        current_price=current_price,
        ma500=ma500,
        ma1000=ma1000,
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
            },
            "period_scores": period_scores,
            "technical_details": technical_details,
            "macro_details": macro_details,
            "event_details": event_details,
            "event_count": event_count,
            "price_history": price_history,
            "price_series": market_service.build_price_series_with_ma(price_history),
        }
    )
    _cached_snapshot[key] = snapshot
    _cached_at[key] = now
    return snapshot


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
def evaluate_sp500(position: PositionRequest):
    try:
        return get_cached_snapshot(position.index_type)
    except Exception:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=502, detail="Evaluation failed")


@app.post("/api/evaluate")
def evaluate(position: PositionRequest):
    try:
        return get_cached_snapshot(position.index_type)
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
