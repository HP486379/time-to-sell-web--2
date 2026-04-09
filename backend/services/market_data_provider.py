from __future__ import annotations

from datetime import date, timedelta
from typing import List, Tuple

import logging
import os
import pandas as pd
import requests

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 12
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
FETCH_API_BASE = os.getenv("MARKET_FETCH_API_BASE", "http://127.0.0.1:9000")


def _build_direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_HEADERS)
    session.proxies.clear()
    return session


def _extract_close_series(hist: pd.DataFrame) -> pd.Series:
    close = hist.get("Close")
    if close is None:
        close = hist.get("Adj Close")
    if close is None:
        raise ValueError("close column missing")
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def _fetch_from_gateway(provider: str, symbol: str, start: date, end: date) -> pd.Series | None:
    if not FETCH_API_BASE:
        raise ValueError("MARKET_FETCH_API_BASE is required")
    session = _build_direct_session()
    url = f"{FETCH_API_BASE.rstrip('/')}/fetch"
    resp = session.get(
        url,
        params={
            "provider": provider,
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
        },
        proxies={},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    payload = resp.json()
    prices = payload.get("prices") if isinstance(payload, dict) else None
    if not isinstance(prices, list) or not prices:
        raise ValueError(f"gateway empty prices provider={provider} symbol={symbol}")
    dates = pd.to_datetime([str(item["date"]) for item in prices])
    values = [float(item["close"]) for item in prices]
    series = pd.Series(values, index=dates).dropna()
    logger.info("provider=gateway upstream=%s symbol=%s result=success points=%d", provider, symbol, len(series))
    return series


def fetch_history_from_yfinance(symbol: str, start: date, end: date, session: requests.Session | None = None) -> pd.Series:
    gateway_series = _fetch_from_gateway("yfinance", symbol, start, end)
    if gateway_series is None:
        raise ValueError(f"gateway empty history for {symbol}")
    return gateway_series


def fetch_history_from_nav_api(base_url: str, symbol: str, price_type: str, start: date, end: date) -> List[Tuple[str, float]]:
    session = _build_direct_session()
    resp = session.get(
        f"{base_url.rstrip('/')}/history",
        params={
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_type": price_type,
        },
        proxies={},
        timeout=DEFAULT_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    if not isinstance(data, list):
        raise ValueError("invalid nav_api payload")
    series = [
        (str(item["date"]), float(item["close"]))
        for item in data
        if isinstance(item, dict) and "date" in item and "close" in item
    ]
    if not series:
        raise ValueError("empty nav_api history")
    logger.info("provider=nav_api symbol=%s result=success points=%d", symbol, len(series))
    return series


def _fetch_from_stooq(stooq_symbol: str, start: date, end: date) -> pd.Series:
    gateway_series = _fetch_from_gateway("stooq", stooq_symbol, start, end)
    if gateway_series is None:
        raise ValueError(f"gateway empty history for {stooq_symbol}")
    return gateway_series


def fetch_history_from_stooq(symbol: str, start: date, end: date) -> pd.Series:
    symbol_map = {
        "^GSPC": "^spx",
        "SP500": "^spx",
        "^N225": "^nkx",
        "NIKKEI225": "^nkx",
        "^TOPX": "^tpx",
        "TOPIX": "^tpx",
        "^NSEI": "^nifty",
        "NIFTY50": "^nifty",
    }
    stooq_symbol = symbol_map.get(symbol, symbol.lower())
    return _fetch_from_stooq(stooq_symbol, start, end)


def fetch_fx_from_stooq(symbol: str, start: date, end: date) -> pd.Series:
    symbol_map = {
        "JPY=X": "usdjpy",
        "USDJPY=X": "usdjpy",
        "USDJPY": "usdjpy",
    }
    stooq_symbol = symbol_map.get(symbol, symbol.lower())
    return _fetch_from_stooq(stooq_symbol, start, end)
