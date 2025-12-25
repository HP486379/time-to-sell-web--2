import logging
import os
import random
from datetime import date, timedelta
from typing import List, Optional, Tuple

import requests
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv


logger = logging.getLogger(__name__)


class SP500MarketService:
    """Service that fetches live pricing via yfinance with an optional synthetic fallback."""

    def __init__(self, symbol: Optional[str] = None):
        load_dotenv()
        self.symbol_map = {
            "SP500": symbol or os.getenv("SP500_SYMBOL", "^GSPC"),
            "TOPIX": os.getenv("TOPIX_SYMBOL", "1306.T"),
            "NIKKEI": os.getenv("NIKKEI_SYMBOL", "^N225"),
            "NIFTY50": os.getenv("NIFTY50_SYMBOL", "^NSEI"),
            # オルカンは MSCI ACWI 連動 ETF（ACWI）をプロキシとして利用する
            "ORUKAN": os.getenv("ORUKAN_SYMBOL", "ACWI"),
            # オルカン円建ては ACWI × USD/JPY を用いる
            "orukan_jpy": os.getenv("ORUKAN_JPY_SYMBOL", os.getenv("ORUKAN_SYMBOL", "ACWI")),
            # S&P500 円建ては ^GSPC × USD/JPY を用いる
            "sp500_jpy": os.getenv("SP500_JPY_SYMBOL", os.getenv("SP500_SYMBOL", "^GSPC")),
        }

        self.fx_symbol_map = {
            "orukan_jpy": os.getenv("ORUKAN_JPY_FX_SYMBOL", "JPY=X"),
            "sp500_jpy": os.getenv("SP500_JPY_FX_SYMBOL", "JPY=X"),
        }

        self.price_type_map = {
            "SP500": os.getenv("SP500_PRICE_TYPE", "index"),
            "TOPIX": os.getenv("TOPIX_PRICE_TYPE", "index"),
            "NIKKEI": os.getenv("NIKKEI_PRICE_TYPE", "index"),
            "NIFTY50": os.getenv("NIFTY50_PRICE_TYPE", "index"),
            "ORUKAN": "index",
            "orukan_jpy": "index_jpy",
            "sp500_jpy": "index_jpy",
        }

        self.nav_api_map = {
            "SP500": os.getenv("SP500_NAV_API_BASE"),
            "TOPIX": os.getenv("TOPIX_NAV_API_BASE"),
            "NIKKEI": os.getenv("NIKKEI_NAV_API_BASE"),
            "NIFTY50": os.getenv("NIFTY50_NAV_API_BASE"),
        }

        self.allow_synth_map = {
            "SP500": self._flag("SP500_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "TOPIX": self._flag("TOPIX_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "NIKKEI": self._flag("NIKKEI_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "NIFTY50": self._flag("NIFTY50_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "ORUKAN": True,
            "orukan_jpy": True,
            "sp500_jpy": True,
        }

        self.start_prices = {
            "SP500": 4000.0,
            "TOPIX": 1500.0,
            "NIKKEI": 15000.0,
            "NIFTY50": 4000.0,
            "ORUKAN": 15000.0,
            "orukan_jpy": 15000.0,
            "sp500_jpy": 4000.0,
        }

        logger.info(
            "[MARKET CONFIG] symbols=%s fx_symbols=%s fallback=%s price_types=%s",
            self.symbol_map,
            self.fx_symbol_map,
            self.allow_synth_map,
            self.price_type_map,
        )

    def _extract_close_series(self, hist: pd.DataFrame) -> pd.Series:
        """Extract a 1-D close/adj close series from yfinance DataFrame."""

        close = hist.get("Close")
        if close is None:
            close = hist.get("Adj Close")
        if close is None:
            raise ValueError("close column missing")
        # yfinance may return a DataFrame when using MultiIndex columns; squeeze to Series
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()

    def _flag(self, name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.lower() in {"1", "true", "yes", "on"}

    def _resolve_symbol(self, index_type: str) -> str:
        return self.symbol_map.get(index_type, self.symbol_map["SP500"])

    def _resolve_fx_symbol(self, index_type: str) -> Optional[str]:
        return self.fx_symbol_map.get(index_type)

    def _resolve_nav_base(self, index_type: str) -> Optional[str]:
        return self.nav_api_map.get(index_type)

    def _allow_synthetic_for_index(self, index_type: str) -> bool:
        return self.allow_synth_map.get(index_type, True)

    def _resolve_price_type(self, index_type: str) -> Optional[str]:
        return self.price_type_map.get(index_type)

    def _download_close_series(self, symbol: str, start: date, end: date) -> pd.Series:
        hist = yf.download(symbol, start=start, end=end + timedelta(days=1), interval="1d")
        hist = hist.dropna()
        closes = self._extract_close_series(hist)
        if closes.empty:
            raise ValueError(f"empty history for {symbol}")
        return closes

    def _fetch_index_history_jpy(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        symbol = self._resolve_symbol(index_type)
        fx_symbol = self._resolve_fx_symbol(index_type)
        if not fx_symbol:
            raise ValueError("fx_symbol required for index_jpy")

        idx_close = self._download_close_series(symbol, start, end).rename("close_usd")
        fx_close = self._download_close_series(fx_symbol, start, end).rename("usdjpy")

        combined = pd.concat([idx_close, fx_close], axis=1, join="inner").dropna()
        if combined.empty:
            raise ValueError("no overlapping dates for index and fx")

        combined["close"] = combined["close_usd"] * combined["usdjpy"]
        series = [(self._to_iso_date(idx), round(float(val), 2)) for idx, val in combined["close"].items()]
        logger.info(
            "Using yfinance history for %s (symbol=%s fx_symbol=%s price_type=%s points=%d)",
            index_type,
            symbol,
            fx_symbol,
            self._resolve_price_type(index_type),
            len(series),
        )
        return series

    def _fetch_nav_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        """Optional custom NAV API (if provided by env) returning date/close pairs."""

        nav_base = self._resolve_nav_base(index_type)
        if not nav_base:
            return []

        symbol = self._resolve_symbol(index_type)
        price_type = self._resolve_price_type(index_type)

        try:
            resp = requests.get(
                f"{nav_base.rstrip('/')}/history",
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
            if isinstance(data, list) and data:
                series = [
                    (str(item["date"]), float(item["close"]))
                    for item in data
                    if "date" in item and "close" in item
                ]
                logger.info(
                    "[NAV API] index=%s symbol=%s price_type=%s points=%d",
                    index_type,
                    symbol,
                    price_type,
                    len(series),
                )
                return series
        except Exception as exc:
            logger.warning("NAV API fallback due to error: %s", exc)
        return []

    def _fallback_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        """決定的で過度に膨らまないシンセティック履歴を生成する。

        * 年率のドリフトは指数ごとに設定（S&P500: 約7%、TOPIX: 約4%）
        * 日次の揺らぎを小さめに入れて最大ドローダウンが0%にならないようにする
        * 週末はスキップし、営業日ベースで積み上げる
        """

        annual_drift_map = {
            "SP500": 0.07,
            "TOPIX": 0.04,
            "NIKKEI": 0.05,
            "NIFTY50": 0.08,
            "ORUKAN": 0.06,
            "orukan_jpy": 0.06,
            "sp500_jpy": 0.07,
        }
        annual_drift = annual_drift_map.get(index_type, 0.05)
        daily_drift = annual_drift / 260.0

        rng_seed = f"{index_type}:{start.isoformat()}:{end.isoformat()}"
        rng = random.Random(rng_seed)

        history: List[Tuple[str, float]] = []
        price = self.start_prices.get(index_type, 4000.0)

        current = start
        while current <= end:
            if current.weekday() < 5:  # 月〜金のみ
                noise = rng.uniform(-0.006, 0.006)  # ±0.6% 程度の揺らぎ
                # 半年ごとに5%程度の調整を入れて drawdown を作る
                if (current.timetuple().tm_yday // 182) % 2 == 1:
                    noise -= 0.002

                daily_change = 1 + daily_drift + noise
                price = max(1.0, price * daily_change)
                history.append((current.isoformat(), round(price, 2)))
            current += timedelta(days=1)

        return history

    def _to_iso_date(self, idx) -> str:
        try:
            return idx.date().isoformat()
        except AttributeError:
            try:
                # pandas Timestamp may expose .to_pydatetime
                return idx.to_pydatetime().date().isoformat()  # type: ignore[attr-defined]
            except Exception:
                return str(idx)

    def get_price_history(self, index_type: str = "SP500") -> List[Tuple[str, float]]:
        today = date.today()
        start = today - timedelta(days=365 * 5)
        allow_synth = self._allow_synthetic_for_index(index_type)
        try:
            price_type = self._resolve_price_type(index_type)
            if price_type == "index_jpy":
                return self._fetch_index_history_jpy(start, today, index_type)

            nav_hist = self._fetch_nav_history(start, today, index_type)
            if nav_hist:
                logger.info(
                    "Using NAV history for %s (symbol=%s price_type=%s points=%d)",
                    index_type,
                    self._resolve_symbol(index_type),
                    price_type,
                    len(nav_hist),
                )
                return [(d, round(v, 2)) for d, v in nav_hist]

            symbol = self._resolve_symbol(index_type)
            closes = self._download_close_series(symbol, start, today)
            logger.info(
                "Using yfinance history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                symbol,
                price_type,
                len(closes),
            )
            return [(self._to_iso_date(idx), round(float(val), 2)) for idx, val in closes.items()]
        except Exception as exc:
            logger.warning("Price history fetch failed (%s)", exc, exc_info=True)
            if not allow_synth:
                raise
            fallback = self._fallback_history(start, today, index_type)
            logger.info(
                "Using synthetic history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                self._resolve_symbol(index_type),
                self._resolve_price_type(index_type),
                len(fallback),
            )
            return fallback

    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ) -> List[Tuple[str, float]]:
        allow_synth = self._allow_synthetic_for_index(index_type)
        fallback_allowed = allow_fallback and allow_synth
        try:
            price_type = self._resolve_price_type(index_type)
            if price_type == "index_jpy":
                return self._fetch_index_history_jpy(start, end, index_type)

            nav_hist = self._fetch_nav_history(start, end, index_type)
            if nav_hist:
                logger.info(
                    "Using NAV history for %s (symbol=%s price_type=%s points=%d)",
                    index_type,
                    self._resolve_symbol(index_type),
                    price_type,
                    len(nav_hist),
                )
                return [(d, round(v, 2)) for d, v in nav_hist]

            symbol = self._resolve_symbol(index_type)
            hist = yf.download(symbol, start=start, end=end + timedelta(days=1), interval="1d")
            hist = hist.dropna()
            if hist.empty:
                raise ValueError("empty history")
            closes = self._extract_close_series(hist)
            logger.info(
                "Using yfinance history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                symbol,
                price_type,
                len(closes),
            )
            return [(self._to_iso_date(idx), round(float(val), 2)) for idx, val in closes.items()]
        except Exception as exc:
            logger.warning("Price history fetch failed (%s)", exc, exc_info=True)
            if not fallback_allowed:
                raise
            fallback = self._fallback_history(start, end, index_type)
            logger.info(
                "Using synthetic history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                self._resolve_symbol(index_type),
                self._resolve_price_type(index_type),
                len(fallback),
            )
            return fallback

    def get_usd_jpy(self) -> float:
        try:
            fx = yf.download("JPY=X", period="5d", interval="1d")
            fx = fx.dropna()
            if not fx.empty:
                return round(float(fx["Close"].iloc[-1]), 4)
        except Exception:
            pass
        return 150.0

    def get_fund_nav_jpy(self, sp_price_usd: float, usd_jpy: float) -> float:
        """
        eMAXIS Slim 米国株式（S&P500）の直近基準価額を取得する。

        Yahoo! Finance 上のファンドコード（デフォルト: 03311187.T）を優先し、
        取得できない場合は S&P500 指数を為替で円換算した値でフォールバックする。
        """

        fund_symbol = os.getenv("SP500_FUND_SYMBOL", "03311187.T")
        try:
            fund = yf.download(fund_symbol, period="1mo", interval="1d")
            fund = fund.dropna()
            if not fund.empty:
                return round(float(fund["Close"].iloc[-1]), 2)
        except Exception:
            pass

        return round(sp_price_usd * usd_jpy, 2)

    def get_current_price(
        self, history: Optional[List[Tuple[str, float]]] = None, index_type: str = "SP500"
    ) -> float:
        price_type = self._resolve_price_type(index_type)
        try:
            if price_type == "index_jpy":
                symbol = self._resolve_symbol(index_type)
                fx_symbol = self._resolve_fx_symbol(index_type)
                ticker = yf.Ticker(symbol)
                fx_ticker = yf.Ticker(fx_symbol) if fx_symbol else None
                live = ticker.fast_info.get("lastPrice") if ticker.fast_info else None
                fx_live = fx_ticker.fast_info.get("lastPrice") if fx_ticker and fx_ticker.fast_info else None
                if live and fx_live:
                    return round(float(live) * float(fx_live), 2)

                hist = ticker.history(period="5d", interval="1d")
                fx_hist = fx_ticker.history(period="5d", interval="1d") if fx_ticker else None
                if not hist.empty and fx_hist is not None and not fx_hist.empty:
                    return round(float(hist["Close"].iloc[-1]) * float(fx_hist["Close"].iloc[-1]), 2)
            else:
                ticker = yf.Ticker(self._resolve_symbol(index_type))
                live = ticker.fast_info.get("lastPrice") if ticker.fast_info else None
                if live:
                    return round(float(live), 2)
                hist = ticker.history(period="5d", interval="1d")
                if not hist.empty:
                    return round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass

        if history:
            return history[-1][1]
        today = date.today()
        synthetic = self._fallback_history(today - timedelta(days=30), today, index_type)
        return synthetic[-1][1]

    def build_price_series_with_ma(self, history: List[Tuple[str, float]]):
        closes = [p[1] for p in history]
        dates = [p[0] for p in history]

        def moving_avg(window: int) -> List[Optional[float]]:
            results: List[Optional[float]] = []
            running_sum = 0.0
            for i, price in enumerate(closes):
                running_sum += price
                if i >= window:
                    running_sum -= closes[i - window]
                if i + 1 >= window:
                    results.append(round(running_sum / window, 2))
                else:
                    results.append(None)
            return results

        ma20 = moving_avg(20)
        ma60 = moving_avg(60)
        ma200 = moving_avg(200)

        series = []
        for idx, date_str in enumerate(dates):
            series.append(
                {
                    "date": date_str,
                    "close": closes[idx],
                    "ma20": ma20[idx],
                    "ma60": ma60[idx],
                    "ma200": ma200[idx],
                }
            )
        return series
