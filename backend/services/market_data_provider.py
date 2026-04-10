from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
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
DEFAULT_FETCH_API_BASE = "http://127.0.0.1:9000"


def _build_direct_session() -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_HEADERS)
    session.proxies.clear()
    return session


def _fetch_api_base() -> str:
    return os.getenv("MARKET_FETCH_API_BASE", DEFAULT_FETCH_API_BASE).strip()


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
    fetch_api_base = _fetch_api_base()
    if not fetch_api_base:
        raise ValueError("MARKET_FETCH_API_BASE is required")
    session = _build_direct_session()
    url = f"{fetch_api_base.rstrip('/')}/fetch"
    try:
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
        logger.info(
            "provider=gateway upstream=%s symbol=%s result=success points=%d first=%s last=%s",
            provider,
            symbol,
            len(series),
            float(series.iloc[0]) if len(series) else None,
            float(series.iloc[-1]) if len(series) else None,
        )
        return series
    except Exception as exc:
        logger.warning(
            "provider=gateway upstream=%s symbol=%s result=failed base=%s error=%s",
            provider,
            symbol,
            fetch_api_base,
            exc,
        )
        return None


def _fetch_from_yfinance_direct(symbol: str, start: date, end: date, session: requests.Session | None = None) -> pd.Series:
    import yfinance as yf

    hist = yf.download(
        symbol,
        start=start,
        end=end + timedelta(days=1),
        interval="1d",
        progress=False,
        auto_adjust=False,
        threads=False,
        timeout=DEFAULT_TIMEOUT,
        session=session,
    )
    closes = _extract_close_series(hist.dropna())
    if closes.empty:
        raise ValueError(f"empty history for {symbol}")
    logger.info(
        "provider=yfinance symbol=%s result=success points=%d first=%s last=%s",
        symbol,
        len(closes),
        float(closes.iloc[0]),
        float(closes.iloc[-1]),
    )
    return closes


def _fetch_from_stooq_direct(stooq_symbol: str, start: date, end: date) -> pd.Series:
    session = _build_direct_session()
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
    resp = session.get(url, timeout=DEFAULT_TIMEOUT, proxies={})
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise ValueError(f"stooq response invalid for {stooq_symbol}")
    df["Date"] = pd.to_datetime(df["Date"])
    mask = (df["Date"].dt.date >= start) & (df["Date"].dt.date <= end)
    sliced = df.loc[mask, ["Date", "Close"]].dropna().sort_values("Date")
    if sliced.empty:
        raise ValueError(f"empty stooq history for {stooq_symbol}")
    series = pd.Series(sliced["Close"].values, index=sliced["Date"])
    logger.info(
        "provider=stooq symbol=%s result=success points=%d first=%s last=%s",
        stooq_symbol,
        len(series),
        float(series.iloc[0]),
        float(series.iloc[-1]),
    )
    return series


def fetch_history_from_yfinance(symbol: str, start: date, end: date, session: requests.Session | None = None) -> pd.Series:
    gateway_series = _fetch_from_gateway("yfinance", symbol, start, end)
    if gateway_series is not None:
        return gateway_series
    return _fetch_from_yfinance_direct(symbol, start, end, session=session)


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
    if gateway_series is not None:
        return gateway_series
    return _fetch_from_stooq_direct(stooq_symbol, start, end)


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
