from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import List, Optional
from pathlib import Path
import logging
from enum import Enum

from fastapi import FastAPI, HTTPException, Query, Header
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
from services.event_service import EventService, load_manual_events
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
    return value


class PositionRequest(BaseModel):
    index_type: IndexType = IndexType.SP500
    total_quantity: int = 0
    avg_cost: float = 0.0
    score_ma: int = Field(200, description="スコア計算に使う移動平均日数")


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


class EvaluateResponse(BaseModel):
    current_price: float
    scores: ScoreBreakdown
    price_history: List[PricePoint]
    event_details: dict
    event_adjustment_pt: float = 0.0
    event_count: int = 0
    price_series: List[PricePoint]


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

# 手動イベント JSON のパス（例: backend/data/us_events.json）
MANUAL_EVENTS_PATH = Path(__file__).parent / "data" / "us_events.json"

MANUAL_EVENTS_PATH = Path(__file__).parent / "data" / "us_events.json"

market_service = SP500MarketService()
price_history_service = PriceHistoryService(market_service, ttl=timedelta(minutes=15))
macro_service = MacroDataService()

# 手動イベント JSON をロード
MANUAL_EVENTS_PATH = Path(__file__).parent / "data" / "us_events.json"
manual_events = load_manual_events(MANUAL_EVENTS_PATH)

event_service = EventService(manual_events=manual_events)
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
        serialized["events"] = [_serialize_event(event) for event in events if isinstance(event, dict)]
    return serialized

# ======================
# Cache
# ======================

_cache_ttl = timedelta(seconds=60)
_cached_snapshot = {}
_cached_at: dict[str, datetime] = {}
MIN_PRICE_POINTS = 200


# ======================
# Time & Helpers
# ======================

def get_cached_snapshot(index_type: IndexType) -> dict:
    """
    インデックスごとのスナップショットを返すヘルパー。
    ※ 実装はプロジェクトの既存ロジックに合わせて、
      SP500MarketService / MacroDataService / EventService を使う。
    """
    # ここは既存 main.py と同等の実装で OK。
    # 必要に応じてキャッシュ（lru_cache 等）を入れてもよい。
    price_history = market_service.get_price_history(index_type.value)
    macro_snapshot = macro_service.get_macro_series()
    today = date.today()
    events = event_service.get_events_for_date(today)

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
# Snapshot Builder
# ======================

def _price_history_range():
    today = date.today()
    return today - timedelta(days=365 * 5), today


    technical_score, technical_details = calculate_technical_score(price_history)
    macro_data = macro_service.get_macro_series()
    macro_score, macro_details = calculate_macro_score(
        macro_data["r_10y"], macro_data["cpi"], macro_data["vix"]
    )
    macro_score = calculate_macro_score(macro_snapshot)
    event_adjustment, event_details = calculate_event_adjustment(events)

    events = event_service.get_events()
    event_adjustment, event_details = calculate_event_adjustment(date.today(), events)
    event_details = _serialize_event_details(event_details)

def _get_price_series(index_type: IndexType):
    price_history = _get_price_history(index_type)
    return market_service.build_price_series_with_ma(price_history)

    current_price = price_history[-1][1] if price_history else 0.0
    price_history_points = [
        {"date": price_date, "close": close} for price_date, close in price_history
    ]

    snapshot = {
        "current_price": current_price,
        "price_history": price_history_points,
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
        target = date.today()
        if price_history:
            target = date.fromisoformat(price_history[-1][0])
        event_adjustment, event_details, event_count = _build_event_adjustment(target)
    except Exception:
        logger.exception("[snapshot] events calc failed for %s", index_type.value)
        event_adjustment, event_details, event_count = 0.0, {}, 0

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
            "event_count": event_count,
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


@app.get("/api/sp500-jpy/price-history", response_model=List[PricePoint])
def get_sp500_jpy_history():
    return get_cached_snapshot(IndexType.SP500_JPY)["price_series"]


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
# Snapshot Cache
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


def _evaluate(position: PositionRequest) -> Dict:
    snapshot = get_cached_snapshot(position.index_type)
    current_price = snapshot["current_price"]

    macro_score = snapshot.get("scores", {}).get("macro", 0.0)
    event_adjustment = snapshot.get("scores", {}).get("event_adjustment", 0.0)
    event_details = snapshot.get("event_details", {}) or {}
    event_count = int(snapshot.get("event_count", 0) or 0)

    if not snapshot.get("macro_details"):
        reasons.append("MACRO_UNAVAILABLE")

    try:
        target = date.fromisoformat(price_history[-1][0])
        event_adjustment, event_details, event_count = _build_event_adjustment(target)
    except Exception:
        logger.exception("[evaluate] events calc failed request_id=%s index=%s", request_id, position.index_type.value)
        event_adjustment, event_details, event_count = 0.0, {}, 0

    if not event_details:
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
            0.0,
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
    period_total = max(0.0, min(period_scores[selected_key] + event_adjustment, 100.0))
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

    total_score = max(0.0, min(base_score + bonus + event_adjustment, 100.0))
    label = get_label(total_score)
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

    used_index_type = position.index_type.value
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
                "total": total_score,
                "label": label,
                "period_total": period_total,
            },
            "technical_details": technical_details,
            "macro_details": snapshot.get("macro_details", {}),
            "event_details": event_details,
            "event_adjustment_pt": float(event_adjustment),
            "event_count": int(event_count),
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
    try:
        return _evaluate(position)
    except Exception:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=502, detail="Evaluation failed")


@app.post("/api/evaluate", response_model=EvaluateResponse)
def evaluate(position: PositionRequest):
    try:
        return _evaluate(position)
    except Exception:
        logger.exception("Evaluation failed")
        raise HTTPException(status_code=502, detail="Evaluation failed")


# ======================
# Backtest Endpoint
# ======================


@app.post("/api/backtest")
def backtest(payload: BacktestRequest):
    """
    デバッグ用：まずは CORS ＆ルーティングが正しいかだけ確認する簡易版。
    本番ロジックは一旦コメントアウトしている。
    """
    # ここではバックテストの本当の計算はせず、
    # フロントから受け取った値をそのまま返すだけにしておく。
    return {
        "summary": {
            "final_equity": float(payload.initial_cash),
            "hold_equity": float(payload.initial_cash),
            "total_return": 0.0,
            "max_drawdown": 0.0,
            "trade_count": 0,
        },
        "equity_curve": [],
    }


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
