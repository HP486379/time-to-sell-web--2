from __future__ import annotations

from datetime import date, timedelta
from io import StringIO
from typing import Literal

import logging
import pandas as pd
import requests
import yfinance as yf
from fastapi import FastAPI, HTTPException, Query

app = FastAPI(title="Market Fetcher Service", version="1.0.0")
logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 12
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    )
}


def _extract_close_series(hist: pd.DataFrame) -> pd.Series:
    close = hist.get("Close")
    if close is None:
        close = hist.get("Adj Close")
    if close is None:
        raise ValueError("close column missing")
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    return close.dropna()


def _fetch_yfinance(symbol: str, start: date, end: date) -> pd.Series:
    symbol_map = {
        "SP500": "^GSPC",
        "NIKKEI225": "^N225",
        "TOPIX": "^TOPX",
        "NIFTY50": "^NSEI",
        "USDJPY": "JPY=X",
    }
    yf_symbol = symbol_map.get(symbol, symbol)
    hist = yf.download(
        yf_symbol,
        start=start,
        end=end + timedelta(days=1),
        interval="1d",
        progress=False,
        threads=False,
        timeout=DEFAULT_TIMEOUT,
    )
    closes = _extract_close_series(hist.dropna())
    if closes.empty:
        raise ValueError(f"empty history for {yf_symbol}")
    logger.info(
        "provider=yfinance symbol=%s result=success points=%d first=%s last=%s",
        yf_symbol,
        len(closes),
        float(closes.iloc[0]),
        float(closes.iloc[-1]),
    )
    return closes


def _stooq_symbol(symbol: str) -> str:
    symbol_map = {
        "^GSPC": "^spx",
        "SP500": "^spx",
        "^N225": "^nkx",
        "NIKKEI225": "^nkx",
        "^TOPX": "^tpx",
        "TOPIX": "^tpx",
        "^NSEI": "^nifty",
        "NIFTY50": "^nifty",
        "JPY=X": "usdjpy",
        "USDJPY=X": "usdjpy",
    }
    return symbol_map.get(symbol, symbol.lower())


def _fetch_stooq(symbol: str, start: date, end: date) -> pd.Series:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_HEADERS)
    session.proxies.clear()
    normalized = _stooq_symbol(symbol)
    url = f"https://stooq.com/q/d/l/?s={normalized}&i=d"
    resp = session.get(url, timeout=DEFAULT_TIMEOUT, proxies={})
    resp.raise_for_status()
    df = pd.read_csv(StringIO(resp.text))
    if "Date" not in df.columns or "Close" not in df.columns:
        raise ValueError(f"stooq response invalid for {normalized}")
    df["Date"] = pd.to_datetime(df["Date"])
    mask = (df["Date"].dt.date >= start) & (df["Date"].dt.date <= end)
    sliced = df.loc[mask, ["Date", "Close"]].dropna().sort_values("Date")
    if sliced.empty:
        raise ValueError(f"empty stooq history for {normalized}")
    series = pd.Series(sliced["Close"].values, index=sliced["Date"])
    logger.info(
        "provider=stooq symbol=%s result=success points=%d first=%s last=%s",
        normalized,
        len(series),
        float(series.iloc[0]),
        float(series.iloc[-1]),
    )
    return series


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/fetch")
def fetch_prices(
    provider: Literal["stooq", "yfinance", "auto"] = Query("auto"),
    symbol: str = Query(...),
    start: date | None = Query(None),
    end: date | None = Query(None),
):
    if end is None:
        end = date.today()
    if start is None:
        start = end - timedelta(days=365 * 5)
    # SP500 だけは一時的に yfinance を除外し、stooq 経路を強制する
    if symbol == "SP500":
        providers = ["stooq"]
    else:
        providers = ["stooq", "yfinance"] if provider == "auto" else [provider]
    last_error: Exception | None = None
    for p in providers:
        try:
            series = _fetch_stooq(symbol, start, end) if p == "stooq" else _fetch_yfinance(symbol, start, end)
            prices = [{"date": idx.date().isoformat(), "close": round(float(v), 2)} for idx, v in series.items()]
            logger.info(
                "fetch provider=%s symbol=%s result=success points=%d first=%s last=%s",
                p,
                symbol,
                len(prices),
                prices[0]["close"] if prices else None,
                prices[-1]["close"] if prices else None,
            )
            return {"symbol": symbol, "provider": p, "prices": prices}
        except Exception as exc:
            logger.warning("fetch provider=%s symbol=%s result=failed error=%s", p, symbol, exc)
            last_error = exc
            continue
    raise HTTPException(status_code=502, detail=f"fetch_failed:{last_error}")
