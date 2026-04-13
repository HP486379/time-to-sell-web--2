from datetime import date

import pandas as pd
import pytest

from backend.services.market_data_provider import fetch_history_from_yfinance_with_debug


def test_topix_requires_adj_close_column(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    close_only = pd.DataFrame({"Close": [1000.0 + i for i in range(5)]}, index=idx)

    monkeypatch.setattr("backend.services.market_data_provider._fetch_from_gateway", lambda *args, **kwargs: None)
    monkeypatch.setattr("yfinance.download", lambda *args, **kwargs: close_only)

    with pytest.raises(Exception):
        fetch_history_from_yfinance_with_debug("1306.T", date(2024, 1, 1), date(2024, 1, 31), prefer_adj_close=True)


def test_topix_ignores_gateway_close_only_series(monkeypatch):
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    gateway_close = pd.Series([1.0, 2.0, 3.0], index=idx)
    direct = pd.DataFrame({"Adj Close": [390.0, 395.0, 400.0]}, index=idx)

    monkeypatch.setattr("backend.services.market_data_provider._fetch_from_gateway", lambda *args, **kwargs: gateway_close)
    monkeypatch.setattr("yfinance.download", lambda *args, **kwargs: direct)

    series, meta = fetch_history_from_yfinance_with_debug("1306.T", date(2024, 1, 1), date(2024, 1, 31), prefer_adj_close=True)

    assert float(series.iloc[-1]) == 400.0
    assert meta.get("source_path") == "direct"
    assert meta.get("selected_price_column") == "Adj Close"
