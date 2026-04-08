from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from typing import List, Tuple

import logging
import os
import pandas as pd
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 12
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}
FETCH_API_BASE = os.getenv("MARKET_FETCH_API_BASE", "https://time-to-sell-fetcher.onrender.com")


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
        return None
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
    try:
        gateway_series = _fetch_from_gateway("yfinance", symbol, start, end)
        if gateway_series is not None:
            return gateway_series
    except Exception as exc:
        logger.warning(
            "provider=gateway upstream=yfinance symbol=%s result=error base=%s err=%s fallback=direct",
            symbol,
            FETCH_API_BASE,
            exc,
        )
    try:
        hist = yf.download(
            symbol,
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            progress=False,
            threads=False,
            session=session,
            timeout=DEFAULT_TIMEOUT,
        )
    except Exception as exc:
        if "requires curl_cffi session" not in str(exc):
            logger.warning("provider=yfinance symbol=%s result=error err=%s", symbol, exc)
            raise
        logger.warning("provider=yfinance symbol=%s result=session_incompatible retry_without_session=true", symbol)
        hist = yf.download(
            symbol,
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            progress=False,
            threads=False,
            timeout=DEFAULT_TIMEOUT,
        )
    hist = hist.dropna()
    closes = _extract_close_series(hist)
    if closes.empty:
        raise ValueError(f"empty history for {symbol}")
    logger.info("provider=yfinance symbol=%s result=success points=%d", symbol, len(closes))
    return closes


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
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
    session = _build_direct_session()
    logger.info("provider=stooq symbol=%s result=request_start url=%s", stooq_symbol, url)
    resp = session.get(url, proxies={}, timeout=DEFAULT_TIMEOUT)
    logger.info("provider=stooq symbol=%s result=http status=%s bytes=%d", stooq_symbol, resp.status_code, len(resp.text or ""))
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise ValueError(f"stooq response invalid for {stooq_symbol}")
    df["Date"] = pd.to_datetime(df["Date"])
    mask = (df["Date"].dt.date >= start) & (df["Date"].dt.date <= end)
    sliced = df.loc[mask, ["Date", "Close"]].dropna()
    if sliced.empty:
        raise ValueError(f"empty stooq history for {stooq_symbol}")
    sliced = sliced.sort_values("Date")
    logger.info("provider=stooq symbol=%s result=success points=%d", stooq_symbol, len(sliced))
    return pd.Series(sliced["Close"].values, index=sliced["Date"])


def fetch_history_from_stooq(symbol: str, start: date, end: date) -> pd.Series:
    try:
        gateway_series = _fetch_from_gateway("stooq", symbol, start, end)
        if gateway_series is not None:
            return gateway_series
    except Exception as exc:
        logger.warning(
            "provider=gateway upstream=stooq symbol=%s result=error base=%s err=%s fallback=direct",
            symbol,
            FETCH_API_BASE,
            exc,
        )
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
