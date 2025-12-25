import os
from datetime import date
from typing import Optional, Tuple

import yfinance as yf


class FundNavService:
    def __init__(
        self,
        base_symbol: Optional[str] = None,
        fund_symbol: Optional[str] = None,
    ):
        self.base_symbol = base_symbol or os.getenv("SP500_NAV_BASE_SYMBOL", "VOO")
        self.fund_symbol = fund_symbol or os.getenv("SP500_FUND_SYMBOL", "03311187.T")

    def fetch_sp500_price_usd(self) -> Tuple[float, str]:
        """Fetch the latest close for the S&P500 proxy in USD and its date."""
        try:
            ticker = yf.Ticker(self.base_symbol)
            hist = ticker.history(period="1mo", interval="1d")
            closes = hist["Close"].dropna()
            if not closes.empty:
                last_price = float(closes.iloc[-1])
                last_date = closes.index[-1].date().isoformat()
                return round(last_price, 2), last_date
            live = ticker.fast_info.get("lastPrice") if ticker.fast_info else None
            if live:
                return round(float(live), 2), date.today().isoformat()
        except Exception:
            pass
        return 4500.0, date.today().isoformat()

    def fetch_usdjpy_rate(self) -> Tuple[float, str]:
        try:
            fx = yf.download("JPY=X", period="5d", interval="1d").dropna()
            if not fx.empty:
                return round(float(fx["Close"].iloc[-1]), 4), fx.index[-1].date().isoformat()
        except Exception:
            pass
        return 150.0, date.today().isoformat()

    def compute_synthetic_nav_jpy(self, price_usd: float, usd_jpy: float) -> float:
        return round(price_usd * usd_jpy, 2)

    def fetch_fund_nav_jpy(self) -> Optional[Tuple[float, str]]:
        try:
            fund = yf.download(self.fund_symbol, period="3mo", interval="1d").dropna()
            if not fund.empty:
                nav = float(fund["Close"].iloc[-1])
                nav_date = fund.index[-1].date().isoformat()
                return round(nav, 2), nav_date
        except Exception:
            pass
        return None

    def get_synthetic_nav(self):
        price_usd, price_date = self.fetch_sp500_price_usd()
        usd_jpy, fx_date = self.fetch_usdjpy_rate()
        nav_jpy = self.compute_synthetic_nav_jpy(price_usd, usd_jpy)
        return {
            "asOf": max(price_date, fx_date),
            "priceUsd": price_usd,
            "usdJpy": usd_jpy,
            "navJpy": nav_jpy,
            "source": "synthetic",
        }

    def get_official_nav(self):
        nav = self.fetch_fund_nav_jpy()
        if nav:
            nav_jpy, nav_date = nav
            return {"asOf": nav_date, "navJpy": nav_jpy, "source": "fund"}
        return None
