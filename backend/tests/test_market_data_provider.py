from datetime import date

import pandas as pd

from backend.services import market_data_provider as mdp


def test_fetch_history_from_yfinance_fallbacks_to_direct(monkeypatch):
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    series = pd.Series([100.0, 101.0], index=pd.to_datetime(["2024-01-04", "2024-01-05"]))

    monkeypatch.setattr(mdp, "_fetch_from_gateway", lambda *args, **kwargs: None)
    monkeypatch.setattr(mdp, "_fetch_from_yfinance_direct", lambda *args, **kwargs: series)

    result = mdp.fetch_history_from_yfinance("^GSPC", start, end)

    assert len(result) == 2
    assert float(result.iloc[0]) == 100.0


def test_fetch_history_from_stooq_fallbacks_to_direct(monkeypatch):
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    series = pd.Series([200.0, 201.0], index=pd.to_datetime(["2024-01-04", "2024-01-05"]))

    monkeypatch.setattr(mdp, "_fetch_from_gateway", lambda *args, **kwargs: None)
    monkeypatch.setattr(mdp, "_fetch_from_stooq_direct", lambda *args, **kwargs: series)

    result = mdp.fetch_history_from_stooq("SP500", start, end)

    assert len(result) == 2
    assert float(result.iloc[-1]) == 201.0


def test_fetch_history_from_yfinance_with_debug_prefers_adj_close(monkeypatch):
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    idx = pd.to_datetime(["2024-01-04", "2024-01-05"])
    close = pd.Series([1800.0, 400.0], index=idx)
    adj_close = pd.Series([390.0, 400.0], index=idx)

    monkeypatch.setattr(mdp, "_fetch_from_gateway", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        mdp,
        "_fetch_from_yfinance_direct",
        lambda *args, **kwargs: (adj_close, {"selected_price_column": "Adj Close", "column_names": ["Close", "Adj Close"]}),
    )

    result, debug = mdp.fetch_history_from_yfinance_with_debug("1306.T", start, end, prefer_adj_close=True)
    assert float(result.iloc[0]) == 390.0
    assert debug["selected_price_column"] == "Adj Close"
