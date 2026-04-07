from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from typing import List, Tuple

import pandas as pd
import requests
import yfinance as yf


def _extract_close_series(hist: pd.DataFrame) -> pd.Series:
    close = hist.get("Close")
    if close is None:
        close = hist.get("Adj Close")
    if close is None:
        raise ValueError("close column missing")
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def fetch_history_from_yfinance(symbol: str, start: date, end: date, session: requests.Session | None = None) -> pd.Series:
    try:
        hist = yf.download(
            symbol,
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            progress=False,
            threads=False,
            session=session,
        )
    except Exception as exc:
        if "requires curl_cffi session" not in str(exc):
            raise
        hist = yf.download(
            symbol,
            start=start,
            end=end + timedelta(days=1),
            interval="1d",
            progress=False,
            threads=False,
        )
    hist = hist.dropna()
    closes = _extract_close_series(hist)
    if closes.empty:
        raise ValueError(f"empty history for {symbol}")
    return closes


def fetch_history_from_nav_api(base_url: str, symbol: str, price_type: str, start: date, end: date) -> List[Tuple[str, float]]:
    resp = requests.get(
        f"{base_url.rstrip('/')}/history",
        params={
            "symbol": symbol,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "price_type": price_type,
        },
        timeout=10,
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
    return series


def _fetch_from_stooq(stooq_symbol: str, start: date, end: date) -> pd.Series:
    url = f"https://stooq.com/q/d/l/?s={stooq_symbol}&i=d"
    resp = requests.get(url, timeout=10)
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
    return pd.Series(sliced["Close"].values, index=sliced["Date"])


def fetch_history_from_stooq(symbol: str, start: date, end: date) -> pd.Series:
    symbol_map = {
        "^GSPC": "^spx",
        "SP500": "^spx",
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
