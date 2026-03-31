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
# Standalone Run
# ====================== 


@app.get("/api/purchase")
def purchase(
    payload: PurchaseRequest,
    x_user_id: Optional[str] = Header(None),
):
    """
    iOSアプリからの課金登録エンドポイント。
    X-User-Id ヘッダが存在する場合はそちらを優先し、
    なければ payload.user_id を使用する（冪等性あり）。
    """
    user_id = x_user_id if x_user_id else payload.user_id

    # 未知の product_id は 400
    if payload.product_id not in purchases_store.PRODUCT_TO_INDEX:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown product_id: {payload.product_id}. "+
                   f"Valid values: {list(purchases_store.PRODUCT_TO_INDEX.keys())}",
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


# ====================== 
# Standalone Run
# ====================== 

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
