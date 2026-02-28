import pandas as pd
import yfinance as yf

from backend.services.sp500_market_service import SP500MarketService


def _history_from_values(start: str, values):
    dates = pd.date_range(start, periods=len(values), freq="B")
    return [(d.date().isoformat(), float(v)) for d, v in zip(dates, values)]


def test_get_price_history_range_handles_dataframe(monkeypatch):
    service = SP500MarketService(symbol="TEST")

    dates = pd.date_range("2020-01-01", periods=35, freq="B")
    df = pd.DataFrame({"Close": [100.0 + i for i in range(35)]}, index=dates)

    def fake_download(symbol, start, end, interval):  # pragma: no cover - simple stub
        return df

    monkeypatch.setattr(yf, "download", fake_download)

    history = service.get_price_history_range(dates[0].date(), dates[-1].date(), allow_fallback=False, index_type="UNKNOWN")
    assert history == [(d.date().isoformat(), float(100.0 + i)) for i, d in enumerate(dates)]


def test_validate_history_rejects_abnormal_sp500_price():
    service = SP500MarketService(symbol="TEST")
    history = _history_from_values("2020-01-01", [4100.0 - i * 30 for i in range(40)])

    reason = service._validate_history(history, "SP500")

    assert reason is not None
    assert "abnormal_sp500_price" in reason


def test_get_price_history_range_retries_and_recovers(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = pd.Timestamp("2020-01-01").date()
    end = pd.Timestamp("2020-03-31").date()

    abnormal = _history_from_values("2020-01-01", [4200.0] * 40 + [2000.0])
    normal = _history_from_values("2020-01-01", [4200.0 + i * 2 for i in range(41)])
    responses = [abnormal, normal]

    def fake_fetch(symbol, s, e):
        hist = responses.pop(0)
        dates = pd.to_datetime([d for d, _ in hist])
        values = [v for _, v in hist]
        return pd.Series(values, index=dates)

    monkeypatch.setattr(service, "_download_close_series", fake_fetch)
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=False, index_type="SP500")

    assert history == normal


def test_get_price_history_range_uses_last_good_on_repeated_invalid(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = pd.Timestamp("2020-01-01").date()
    end = pd.Timestamp("2020-03-31").date()

    normal = _history_from_values("2020-01-01", [4100.0 + i * 2 for i in range(41)])
    abnormal = _history_from_values("2020-01-01", [4100.0] * 40 + [2000.0])

    service._last_good_history["SP500"] = normal

    def always_bad(symbol, s, e):
        dates = pd.to_datetime([d for d, _ in abnormal])
        values = [v for _, v in abnormal]
        return pd.Series(values, index=dates)

    monkeypatch.setattr(service, "_download_close_series", always_bad)
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=False, index_type="SP500")

    assert history == normal
