import os
import random
from datetime import date, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv


class MacroDataService:
    """Fetches macro series (10y, CPI, VIX) with live sources and graceful fallbacks."""

    def __init__(self):
        load_dotenv()
        self.fred_api_key = os.getenv("FRED_API_KEY")

    def _extract_close_series(self, df: pd.DataFrame) -> pd.Series:
        close = df.get("Close")
        if close is None:
            close = df.get("Adj Close")
        if close is None:
            raise ValueError("close column missing")
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()

    def _synthetic_series(
        self, base: float, variance: float, points: int = 120, seed_tag: str = "macro"
    ) -> Tuple[List[float], float]:
        rng = random.Random(f"{seed_tag}:{base}:{variance}:{points}")
        history = [round(base + rng.uniform(-variance, variance), 4) for _ in range(points)]
        current = round(base + variance * 0.5, 4)
        return history, current

    def _fetch_fred_series(self, series_id: str, start: date, end: Optional[date] = None) -> List[float]:
        if not self.fred_api_key:
            return []

        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
        }
        if end:
            params["observation_end"] = end.isoformat()
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10
            )
            resp.raise_for_status()
            observations = resp.json().get("observations", [])
            values: List[float] = []
            for obs in observations:
                try:
                    values.append(float(obs["value"]))
                except (TypeError, ValueError):
                    continue
            return values
        except Exception:
            return []

    def _fetch_fred_series_with_dates(
        self, series_id: str, start: date, end: date
    ) -> List[Tuple[date, float]]:
        if not self.fred_api_key:
            return []
        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "observation_start": start.isoformat(),
            "observation_end": end.isoformat(),
        }
        try:
            resp = requests.get(
                "https://api.stlouisfed.org/fred/series/observations", params=params, timeout=10
            )
            resp.raise_for_status()
            observations = resp.json().get("observations", [])
            series: List[Tuple[date, float]] = []
            for obs in observations:
                try:
                    obs_date = date.fromisoformat(obs["date"])
                    series.append((obs_date, float(obs["value"])))
                except Exception:
                    continue
            return series
        except Exception:
            return []

    def _fetch_vix(self) -> Tuple[List[float], float]:
        try:
            ticker = yf.Ticker("^VIX")
            hist = ticker.history(period="2y", interval="1d")
            if hist.empty:
                raise ValueError("empty VIX history")
            closes = hist["Close"].dropna()
            history = [round(float(val), 2) for val in closes[:-1]]
            current = round(float(closes.iloc[-1]), 2)
            return history, current
        except Exception:
            return self._synthetic_series(18.0, 5.0, seed_tag="vix")

    def _fetch_r10y(self) -> Tuple[List[float], float]:
        start = date.today() - timedelta(days=3650)
        values = self._fetch_fred_series("DGS10", start)
        if values:
            return values[:-1], values[-1]
        return self._synthetic_series(3.5, 1.0, seed_tag="r10y")

    def _fetch_cpi(self) -> Tuple[List[float], float]:
        start = date.today() - timedelta(days=3650)
        values = self._fetch_fred_series("CPIAUCSL", start)
        if values:
            return values[:-1], values[-1]
        return self._synthetic_series(4.0, 1.2, seed_tag="cpi")

    def _synthetic_series_with_dates(
        self, start: date, end: date, base: float, variance: float, seed_tag: str
    ) -> List[Tuple[date, float]]:
        days = (end - start).days
        if days <= 0:
            days = 30
        rng = random.Random(
            f"{seed_tag}:{base}:{variance}:{start.isoformat()}:{end.isoformat()}:{days}"
        )
        series: List[Tuple[date, float]] = []
        value = base
        for i in range(days + 1):
            value += rng.uniform(-variance, variance)
            series.append((start + timedelta(days=i), round(value, 3)))
        return series

    def _fetch_vix_range(self, start: date, end: date) -> List[Tuple[date, float]]:
        try:
            data = yf.download("^VIX", start=start, end=end + timedelta(days=1), interval="1d")
            data = data.dropna()
            if data.empty:
                raise ValueError("empty vix range")
            closes = self._extract_close_series(data)
            return [(idx.date(), round(float(val), 3)) for idx, val in closes.items()]
        except Exception:
            return self._synthetic_series_with_dates(start, end, 18.0, 5.0, seed_tag="vix")

    def _fetch_r10y_range(self, start: date, end: date) -> List[Tuple[date, float]]:
        values = []
        if self.fred_api_key:
            values = self._fetch_fred_series_with_dates("DGS10", start, end)
        if not values:
            try:
                data = yf.download("^TNX", start=start, end=end + timedelta(days=1), interval="1d")
                data = data.dropna()
                if not data.empty:
                    closes = self._extract_close_series(data)
                    values = [(idx.date(), round(float(val) / 10, 3)) for idx, val in closes.items()]
            except Exception:
                pass
        if not values:
            values = self._synthetic_series_with_dates(start, end, 3.5, 1.0, seed_tag="r10y")
        return values

    def _fetch_cpi_range(self, start: date, end: date) -> List[Tuple[date, float]]:
        values: List[Tuple[date, float]] = []
        if self.fred_api_key:
            values = self._fetch_fred_series_with_dates("CPIAUCSL", start, end)
        if not values:
            values = self._synthetic_series_with_dates(start, end, 4.0, 1.2, seed_tag="cpi")
        return values

    def get_macro_series_range(self, start: date, end: date) -> Dict[str, List[Tuple[date, float]]]:
        return {
            "r_10y": self._fetch_r10y_range(start, end),
            "cpi": self._fetch_cpi_range(start, end),
            "vix": self._fetch_vix_range(start, end),
        }

    def get_macro_series(self) -> Dict[str, Tuple[List[float], float]]:
        return {
            "r_10y": self._fetch_r10y(),
            "cpi": self._fetch_cpi(),
            "vix": self._fetch_vix(),
        }
