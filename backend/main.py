from datetime import date, datetime, time, timedelta, timezone
from typing import List, Optional
import logging
from enum import Enum
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from scoring.technical import calculate_technical_score
from scoring.macro import calculate_macro_score
from scoring.events import calculate_event_adjustment
from scoring.total_score import calculate_total_score, get_label
from services.sp500_market_service import SP500MarketService
from services.macro_data_service import MacroDataService
from services.event_service import EventService
from services.nav_service import FundNavService
from services.backtest_service import BacktestService


# ======================
# FastAPI & CORS Config
# ======================

app = FastAPI(title="S&P500 Timing API")

# 本番用 CORS（Vercel の URL を後で追加）
# 例: https://time-to-sell-web--2.vercel.app
ALLOWED_ORIGINS = [
    "https://time-to-sell-web--2.vercel.app",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
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


class PricePoint(BaseModel):
    date: str
    close: float
    ma20: Optional[float]
    ma60: Optional[float]
    ma200: Optional[float]


class EvaluateResponse(BaseModel):
    current_price: float
    market_value: float
    unrealized_pnl: float
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
macro_service = MacroDataService()
event_service = EventService()
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

def _build_snapshot(index_type: IndexType = IndexType.SP500):
    price_history = market_service.get_price_history(index_type=index_type.value)
    market_service.get_current_price(price_history, index_type=index_type.value)
    market_service.get_usd_jpy()

    if index_type == IndexType.SP500:
        fund_nav = nav_service.get_official_nav() or nav_service.get_synthetic_nav()
        current_price = fund_nav["navJpy"]
    else:
        current_price = price_history[-1][1]

    technical_score, technical_details = calculate_technical_score(price_history)
    macro_data = macro_service.get_macro_series()
    macro_score, macro_details = calculate_macro_score(
        macro_data["r_10y"], macro_data["cpi"], macro_data["vix"]
    )

    events = event_service.get_events()
    event_adjustment, event_details = calculate_event_adjustment(date.today(), events)

    total_score = calculate_total_score(technical_score, macro_score, event_adjustment)
    label = get_label(total_score)

    snapshot = {
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

    return snapshot


# ======================
# Price History Endpoints
# ======================

@app.get("/api/sp500/price-history", response_model=List[PricePoint])
def get_sp500_history():
    return get_cached_snapshot(IndexType.SP500)["price_series"]


@app.get("/api/topix/price-history", response_model=List[PricePoint])
def get_topix_history():
    return get_cached_snapshot(IndexType.TOPIX)["price_series"]


@app.get("/api/nikkei/price-history", response_model=List[PricePoint])
def get_nikkei_history():
    return get_cached_snapshot(IndexType.NIKKEI)["price_series"]


@app.get("/api/nifty50/price-history", response_model=List[PricePoint])
def get_nifty_history():
    return get_cached_snapshot(IndexType.NIFTY50)["price_series"]


@app.get("/api/orukan/price-history", response_model=List[PricePoint])
def get_orukan_history():
    return get_cached_snapshot(IndexType.ORUKAN)["price_series"]


@app.get("/api/orukan-jpy/price-history", response_model=List[PricePoint])
def get_orukan_jpy_history():
    return get_cached_snapshot(IndexType.ORUKAN_JPY)["price_series"]


@app.get("/api/sp500-jpy/price-history", response_model=List[PricePoint])
def get_sp500_jpy_history():
    return get_cached_snapshot(IndexType.SP500_JPY)["price_series"]


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
    snapshot = get_cached_snapshot(position.index_type)
    current_price = snapshot["current_price"]

    technical_score, technical_details = calculate_technical_score(
        snapshot["price_history"], base_window=position.score_ma
    )
    macro_score = snapshot["scores"]["macro"]
    event_adjustment = snapshot["scores"]["event_adjustment"]
    total_score = calculate_total_score(technical_score, macro_score, event_adjustment)
    label = get_label(total_score)

    market_value = position.total_quantity * current_price
    unrealized_pnl = market_value - (position.total_quantity * position.avg_cost)

    return {
        "current_price": current_price,
        "market_value": round(market_value, 2),
        "unrealized_pnl": round(unrealized_pnl, 2),
        "scores": {
            "technical": technical_score,
            "macro": macro_score,
            "event_adjustment": event_adjustment,
            "total": total_score,
            "label": label,
        },
        "technical_details": technical_details,
        "macro_details": snapshot["macro_details"],
        "event_details": snapshot["event_details"],
        "price_series": snapshot["price_series"],
    }


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


# ======================
# Standalone Run
# ======================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
