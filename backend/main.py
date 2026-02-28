from datetime import date, datetime, time, timedelta, timezone
import uuid
from typing import List, Optional
import logging
from enum import Enum

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

from scoring.technical import calculate_technical_score, calculate_ultra_long_mas
# 超長期(500/1000日)MA評価：暴落局面でのみ連続的にスコア減衰させる内部ロジック（API/UIには露出しない）
from scoring.macro import calculate_macro_score
from scoring.events import calculate_event_adjustment
from scoring.total_score import calculate_total_score, get_label
from services.sp500_market_service import SP500MarketService
from services.price_history_service import PriceHistoryService, PriceHistoryFetchError
from services.macro_data_service import MacroDataService
from services.event_service import EventService
from services.nav_service import FundNavService
from services.backtest_service import BacktestService


# ======================
# FastAPI & CORS Config
# ======================

app = FastAPI(title="S&P500 Timing API")

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
    SP500_JPY = "sp500_jpy"
    TOPIX = "TOPIX"
    NIKKEI = "NIKKEI"
    NIFTY50 = "NIFTY50"
    ORUKAN = "ORUKAN"
    ORUKAN_JPY = "orukan_jpy"


class PositionRequest(BaseModel):
    total_quantity: float
    avg_cost: float
    index_type: IndexType = IndexType.SP500
    score_ma: int = Field(200)
    request_id: Optional[str] = None

    @validator("index_type", pre=True)
    def normalize_index_type(cls, value):
        if isinstance(value, str):
            normalized = value.lower()
            if normalized == "sp500_jpy":
                return IndexType.SP500_JPY
            if normalized == "orukan_jpy":
                return IndexType.ORUKAN_JPY
        return value


class PricePoint(BaseModel):
    date: str
    close: float
    ma20: Optional[float]
    ma60: Optional[float]
    ma200: Optional[float]


class Event(BaseModel):
    name: str
    importance: int
    date: str
    source: Optional[str] = None
    description: Optional[str] = None


class EvaluateResponse(BaseModel):
    current_price: float
    market_value: float
    unrealized_pnl: float
    status: str
    reasons: List[str]
    as_of: str
    request_id: str
    used_index_type: str
    source: str
    currency: str
    unit: str
    symbol: str
    period_scores: dict
    period_meta: dict
    period_breakdowns: dict
    scores: dict
    technical_details: dict
    macro_details: dict
    event_details: dict
    price_series: List[PricePoint]


class SyntheticNavResponse(BaseModel):
    asOf: str
    priceUsd: float
    usdJpy: float
    navJpy: float
    source: str


class FundNavResponse(BaseModel):
    asOf: str
    navJpy: float
    source: str


class BacktestRequest(BaseModel):
    start_date: date
    end_date: date
    initial_cash: float
    buy_threshold: float = 40.0
    sell_threshold: float = 80.0
    index_type: IndexType = IndexType.SP500
    score_ma: int = Field(200)


class Trade(BaseModel):
    action: str
    date: str
    quantity: int
    price: float


class PortfolioPoint(BaseModel):
    date: str
    value: float


class BacktestResponse(BaseModel):
    final_value: float
    buy_and_hold_final: float
    total_return_pct: float
    cagr_pct: float
    max_drawdown_pct: float
    trade_count: int
    trades: List[Trade]
    portfolio_history: List[PortfolioPoint]
    buy_hold_history: List[PortfolioPoint]


# ======================
# Services
# ======================

logger = logging.getLogger(__name__)

market_service = SP500MarketService()
price_history_service = PriceHistoryService(market_service, ttl=timedelta(minutes=15))
macro_service = MacroDataService()
event_service = EventService()          # ← ここは必ず EventService()
nav_service = FundNavService()
backtest_service = BacktestService(market_service, macro_service, event_service)

JST = timezone(timedelta(hours=9))


def to_jst_iso(value: date) -> str:
    return datetime.combine(value, time.min, tzinfo=JST).isoformat()


# ======================
# Cache
# ======================

_cache_ttl = timedelta(seconds=60)
_cached_snapshot = {}
_cached_at: dict[str, datetime] = {}
MIN_PRICE_POINTS = 200


# ======================
# Health Check
# ======================

@app.get("/api/health")
def health():
    return {"status": "ok"}


# ======================
# NAV Endpoints
# ======================

@app.get("/api/nav/sp500-synthetic", response_model=SyntheticNavResponse)
def get_synthetic_nav():
    return nav_service.get_synthetic_nav()


@app.get("/api/nav/emaxis-slim-sp500", response_model=FundNavResponse)
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
# Snapshot Builder
# ======================

def _price_history_range():
    today = date.today()
    return today - timedelta(days=365 * 5), today


def _get_price_history(index_type: IndexType):
    start, end = _price_history_range()
    return price_history_service.get_history(index_type.value, start, end)


def _get_price_series(index_type: IndexType):
    price_history = _get_price_history(index_type)
    return market_service.build_price_series_with_ma(price_history)


def _get_price_series_or_503(index_type: IndexType):
    try:
        return _get_price_series(index_type)
    except PriceHistoryFetchError as exc:
        logger.error("[price-history] failed index=%s error=%s", index_type.value, exc)
        raise HTTPException(
            status_code=503,
            detail={"reason": f"price history unavailable for {index_type.value}"},
        ) from exc


def _resolve_as_of(price_history: List[tuple[str, float]]) -> str:
    if not price_history:
        return datetime.now(timezone.utc).isoformat()
    last_date = price_history[-1][0]
    try:
        parsed = datetime.fromisoformat(str(last_date))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    except ValueError:
        return datetime.now(timezone.utc).isoformat()


def _build_snapshot(index_type: IndexType = IndexType.SP500):
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
        "price_history": [],
        "price_series": [],
    }

    try:
        price_history = _get_price_history(index_type)
    except PriceHistoryFetchError:
        logger.exception("[snapshot] price history unavailable for %s", index_type.value)
        raise

    if not price_history:
        logger.warning("[snapshot] empty price history for %s", index_type.value)
        return snapshot

    market_service.get_current_price(price_history, index_type=index_type.value)
    market_service.get_usd_jpy()

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
        events = event_service.get_events()
        event_adjustment, event_details = calculate_event_adjustment(date.today(), events)
    except Exception:
        logger.exception("[snapshot] events calc failed for %s", index_type.value)
        event_adjustment, event_details = 0.0, {}

    # 超長期ガードに必要なMAのみ内部で計算（APIに露出しない）
    ma500, ma1000 = calculate_ultra_long_mas(price_history)
    guard_price = price_history[-1][1]
    total_score = calculate_total_score(
        technical_score,
        macro_score,
        event_adjustment,
        current_price=guard_price,
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
            "technical_details": technical_details,
            "macro_details": macro_details,
            "event_details": event_details,
            "price_history": price_history,
            "price_series": market_service.build_price_series_with_ma(price_history),
        }
    )
    return snapshot


# ======================
# Price History Endpoints
# ======================

@app.get("/api/sp500/price-history", response_model=List[PricePoint])
def get_sp500_history():
    return _get_price_series_or_503(IndexType.SP500)


@app.get("/api/topix/price-history", response_model=List[PricePoint])
def get_topix_history():
    return _get_price_series_or_503(IndexType.TOPIX)


@app.get("/api/nikkei/price-history", response_model=List[PricePoint])
def get_nikkei_history():
    return _get_price_series_or_503(IndexType.NIKKEI)


@app.get("/api/nifty50/price-history", response_model=List[PricePoint])
def get_nifty_history():
    return _get_price_series_or_503(IndexType.NIFTY50)


@app.get("/api/orukan/price-history", response_model=List[PricePoint])
def get_orukan_history():
    return _get_price_series_or_503(IndexType.ORUKAN)


@app.get("/api/orukan-jpy/price-history", response_model=List[PricePoint])
def get_orukan_jpy_history():
    return _get_price_series_or_503(IndexType.ORUKAN_JPY)


@app.get("/api/sp500-jpy/price-history", response_model=List[PricePoint])
def get_sp500_jpy_history():
    return _get_price_series_or_503(IndexType.SP500_JPY)


# ======================
# Cache Handler
# ======================

def get_cached_snapshot(index_type: IndexType = IndexType.SP500):
    now = datetime.utcnow()
    key = index_type.value

    if key in _cached_snapshot and now - _cached_at.get(key, datetime.min) < _cache_ttl:
        return _cached_snapshot[key]

    _cached_snapshot[key] = _build_snapshot(index_type)
    _cached_at[key] = now
    return _cached_snapshot[key]


# ======================
# Evaluate Endpoints
# ======================

def _evaluate(position: PositionRequest):
    request_id = position.request_id or str(uuid.uuid4())
    logger.info(
        "[evaluate] start request_id=%s index=%s score_ma=%s",
        request_id,
        position.index_type.value,
        position.score_ma,
    )
    try:
        snapshot = get_cached_snapshot(position.index_type)
    except PriceHistoryFetchError as exc:
        logger.error(
            "[evaluate] price history unavailable request_id=%s index=%s error=%s",
            request_id,
            position.index_type.value,
            exc,
        )
        raise HTTPException(
            status_code=503,
            detail={"reason": f"price history unavailable for {position.index_type.value}"},
        ) from exc
    except Exception as exc:
        logger.exception(
            "[evaluate] snapshot failed request_id=%s index=%s error=%s",
            request_id,
            position.index_type.value,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail={"reason": "snapshot_failed", "message": str(exc), "request_id": request_id},
        ) from exc
    current_price = snapshot.get("current_price", 0.0)
    if not snapshot.get("price_history"):
        logger.error("[evaluate] empty price history request_id=%s index=%s", request_id, position.index_type.value)
        raise HTTPException(
            status_code=503,
            detail={"reason": f"price history unavailable for {position.index_type.value}"},
        )

    reasons: list[str] = []
    price_history = snapshot["price_history"]
    price_series = snapshot["price_series"]
    as_of = _resolve_as_of(price_history)

    if not price_series:
        reasons.append("PRICE_HISTORY_EMPTY")
    elif len(price_series) < MIN_PRICE_POINTS:
        reasons.append("PRICE_HISTORY_SHORT")

    macro_score = snapshot.get("scores", {}).get("macro", 0.0)
    event_adjustment = snapshot.get("scores", {}).get("event_adjustment", 0.0)

    if not snapshot.get("macro_details"):
        reasons.append("MACRO_UNAVAILABLE")

    if not snapshot.get("event_details"):
        reasons.append("EVENTS_UNAVAILABLE")

    # 超長期ガードに必要なMAのみ内部で計算（APIに露出しない）
    ma500, ma1000 = calculate_ultra_long_mas(price_history)
    guard_price = price_history[-1][1]
    period_windows = {
        "short": 20,
        "mid": 60,
        "long": 200,
    }
    period_meta = {
        "short_window": period_windows["short"],
        "mid_window": period_windows["mid"],
        "long_window": period_windows["long"],
    }
    technical_scores: dict[str, float] = {}
    period_scores: dict[str, float] = {}
    period_breakdowns: dict[str, dict] = {}
    technical_details = {}
    technical_ok = True
    technical_score = 0.0

    macro_details_snapshot = snapshot.get("macro_details", {}) or {}
    # NOTE: マクロ・イベントは現行ロジックでは期間非依存のため、period_breakdowns に同値を展開する
    macro_M_value = float(macro_details_snapshot.get("M", macro_score) or 0.0)

    for key, window in period_windows.items():
        details: dict = {}
        try:
            score, details = calculate_technical_score(price_history, base_window=window)
            technical_scores[key] = score
            if window == position.score_ma:
                technical_score = score
                technical_details = details
        except Exception:
            logger.exception(
                "[evaluate] technical calc failed request_id=%s index=%s window=%s",
                request_id,
                position.index_type.value,
                window,
            )
            technical_scores[key] = 0.0
            details = {}
            if window == position.score_ma:
                technical_score = 0.0
                technical_details = {}
            technical_ok = False
            reasons.extend(["TECHNICAL_CALC_ERROR", "TECHNICAL_UNAVAILABLE"])

        period_total_score = calculate_total_score(
            technical_scores[key],
            macro_score,
            event_adjustment,
            current_price=guard_price,
            ma500=ma500,
            ma1000=ma1000,
        )
        period_scores[key] = period_total_score

        period_breakdowns[key] = {
            "scores": {
                "technical": float(technical_scores[key]),
                "macro": float(macro_score),
                "event_adjustment": float(event_adjustment),
            },
            "technical_details": {
                "d": float(details.get("d", 0.0) or 0.0),
                "T_base": float(details.get("T_base", 0.0) or 0.0),
                "T_trend": float(details.get("T_trend", 0.0) or 0.0),
                "T_conv_adj": float(details.get("T_conv_adj", 0.0) or 0.0),
                "technical_score_raw": float(technical_scores[key]),
            },
            "macro_details": {
                "macro_M": macro_M_value,
                "M": macro_M_value,
                "p_r": float(macro_details_snapshot.get("p_r", 0.0) or 0.0),
                "p_cpi": float(macro_details_snapshot.get("p_cpi", 0.0) or 0.0),
                "p_vix": float(macro_details_snapshot.get("p_vix", 0.0) or 0.0),
            },
        }
    selected_key = (
        "short"
        if position.score_ma == period_windows["short"]
        else "mid"
        if position.score_ma == period_windows["mid"]
        else "long"
    )
    period_total = period_scores[selected_key]
    base_score = (
        0.2 * period_scores["short"]
        + 0.3 * period_scores["mid"]
        + 0.5 * period_scores["long"]
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

    exit_total = max(0.0, min(base_score + bonus, 100.0))
    label = get_label(base_score)
    logger.info(
        "[evaluate] price history ready request_id=%s index=%s points=%d",
        request_id,
        position.index_type.value,
        len(price_history),
    )

    market_value = position.total_quantity * current_price
    unrealized_pnl = market_value - (position.total_quantity * position.avg_cost)

    if technical_score == 0:
        reasons.append("TECHNICAL_FALLBACK_ZERO")

    status = "ready" if not reasons else "degraded"
    if not technical_ok and "TECHNICAL_UNAVAILABLE" not in reasons:
        reasons.append("TECHNICAL_UNAVAILABLE")

    if status != "ready":
        logger.warning(
            "[evaluate] degraded request_id=%s index=%s reasons=%s",
            request_id,
            position.index_type.value,
            reasons,
        )

    used_index_type = (
        "SP500_JPY" if position.index_type == IndexType.SP500_JPY else
        "ORUKAN_JPY" if position.index_type == IndexType.ORUKAN_JPY else
        position.index_type.value
    )
    price_type = market_service._resolve_price_type(position.index_type.value)
    symbol = market_service._resolve_symbol(position.index_type.value)
    fx_symbol = market_service._resolve_fx_symbol(position.index_type.value)
    series_symbol = f"{symbol}*{fx_symbol}" if fx_symbol else symbol
    currency = "JPY" if price_type == "index_jpy" else "USD"
    unit = "index_jpy" if price_type == "index_jpy" else "index"
    source = "yfinance_fx" if fx_symbol else "yfinance"

    try:
        return {
            "current_price": current_price,
            "market_value": round(market_value, 2),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "status": status,
            "reasons": reasons,
            "as_of": as_of,
            "request_id": request_id,
            "used_index_type": used_index_type,
            "source": source,
            "currency": currency,
            "unit": unit,
            "symbol": series_symbol,
            "period_scores": period_scores,
            "period_meta": period_meta,
            "period_breakdowns": period_breakdowns,
            "scores": {
                "technical": technical_score,
                "macro": macro_score,
                "event_adjustment": event_adjustment,
                "total": base_score,
                "label": label,
                "period_total": period_total,
            },
            "technical_details": technical_details,
            "macro_details": snapshot.get("macro_details", {}),
            "event_details": snapshot.get("event_details", {}),
            "price_series": price_series,
        }
    except Exception as exc:
        logger.exception(
            "[evaluate] response build failed request_id=%s index=%s error=%s",
            request_id,
            position.index_type.value,
            exc,
        )
        raise HTTPException(
            status_code=500,
            detail={"reason": "evaluate_failed", "message": str(exc), "request_id": request_id},
        ) from exc


@app.post("/api/sp500/evaluate", response_model=EvaluateResponse)
def evaluate_sp500(position: PositionRequest):
    return _evaluate(position)


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(position: PositionRequest):
    return _evaluate(position)


# ======================
# Backtest Endpoint
# ======================

@app.post("/api/backtest", response_model=BacktestResponse)
def backtest(payload: BacktestRequest):
    try:
        return backtest_service.run_backtest(
            payload.start_date,
            payload.end_date,
            payload.initial_cash,
            payload.buy_threshold,
            payload.sell_threshold,
            payload.index_type.value,
            payload.score_ma,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception:
        raise HTTPException(
            status_code=502,
            detail="Backtest failed: external data unavailable.",
        )


# =========================
# Events API（デバッグ用）
# =========================

from datetime import date as dt_date  # ★ date型と引数名の衝突回避のため alias

@app.get("/api/events")
def get_events_api(date: Optional[str] = Query(None), date_str: Optional[str] = Query(None)):
    """
    デバッグ用イベント取得API

    - /api/events?date=2026-01-02
    - /api/events?date_str=2026-01-02
    - /api/events   ← 今日基準
    """
    try:
        # 優先順位: date -> date_str -> today
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

        # EventServiceからイベント取得（dictの配列想定）
        events = event_service.get_events_for_date(target)

        # date型が混ざってたらISO文字列へ変換
        for e in events:
            d = e.get("date")
            if isinstance(d, dt_date):
                e["date"] = d.isoformat()

        return {"events": events, "target": target.isoformat(), "manual_count": len(event_service.manual_events)}

    except Exception as e:
        # 既存仕様に合わせて握りつぶし（現状の挙動を維持）
        return {"error": str(e)}


# ======================
# Standalone Run
# ======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
