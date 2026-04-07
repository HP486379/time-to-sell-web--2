import pandas as pd
import yfinance as yf
from datetime import date
import pytest

from backend.services.sp500_market_service import SP500MarketService


def _history_from_values(start: str, values):
    dates = pd.date_range(start, periods=len(values), freq="B")
    return [(d.date().isoformat(), float(v)) for d, v in zip(dates, values)]


def test_get_price_history_range_handles_dataframe(monkeypatch):
    service = SP500MarketService(symbol="TEST")

    dates = pd.date_range("2020-01-01", periods=35, freq="B")
    df = pd.DataFrame({"Close": [1000.0 + i for i in range(35)]}, index=dates)

    def fake_download(symbol, start, end, interval):  # pragma: no cover - simple stub
        return df

    monkeypatch.setattr(yf, "download", fake_download)

    history = service.get_price_history_range(dates[0].date(), dates[-1].date(), allow_fallback=False, index_type="TOPIX")
    assert history == [(d.date().isoformat(), float(1000.0 + i)) for i, d in enumerate(dates)]


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


def test_fallback_history_uses_same_sp500_drift_for_sp500_jpy(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    monkeypatch.setattr("backend.services.sp500_market_service.random.Random.uniform", lambda *_: 0.0)

    sp500 = service._fallback_history(start, end, "SP500")
    sp500_jpy = service._fallback_history(start, end, "SP500_JPY")

    assert len(sp500) == len(sp500_jpy)
    expected_scale = service.start_prices["SP500_JPY"] / service.start_prices["SP500"]
    assert sp500_jpy[-1][1] == pytest.approx(sp500[-1][1] * expected_scale, abs=1.0)


def test_fallback_history_alias_and_canonical_match(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)

    canonical = service._fallback_history(start, end, "SP500_JPY")
    alias = service._fallback_history(start, end, "sp500_jpy")

    assert canonical == alias


def test_unknown_index_type_warns_and_falls_back(caplog):
    service = SP500MarketService(symbol="TEST")
    with caplog.at_level("WARNING"):
        symbol = service._resolve_symbol("UNKNOWN_INDEX")
    assert symbol == "TEST"
    assert "Unknown index_type" in caplog.text


def test_validate_history_accepts_sp500_jpy_realistic_scale():
    service = SP500MarketService(symbol="TEST")
    history = _history_from_values("2024-01-01", [650000.0 + i * 500 for i in range(50)])

    reason = service._validate_history(history, "SP500_JPY")

    assert reason is None


def test_fallback_sp500_jpy_is_built_from_sp500_and_fx(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 1, 10)

    monkeypatch.setattr(service, "_fallback_fx_history", lambda s, e, _: _history_from_values("2024-01-01", [150.0] * 8))

    sp500 = service._fallback_history(start, end, "SP500")
    sp500_jpy = service._fallback_history(start, end, "SP500_JPY")

    assert len(sp500) == len(sp500_jpy)
    for (d1, p_usd), (d2, p_jpy) in zip(sp500, sp500_jpy):
        assert d1 == d2
        assert p_jpy == pytest.approx(p_usd * 150.0, abs=1.0)


def test_invalid_fallback_uses_last_good_history(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    last_good = _history_from_values("2024-01-01", [1500.0 + i for i in range(60)])
    service._last_good_history["TOPIX"] = last_good

    monkeypatch.setattr(
        service,
        "_fallback_history",
        lambda s, e, index_type: _history_from_values("2024-01-01", [1500.0, 500.0]),
    )

    history = service._build_valid_fallback_history(start, end, "TOPIX")
    assert history == last_good


def test_invalid_fallback_without_last_good_is_data_unavailable(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)

    monkeypatch.setattr(
        service,
        "_fallback_history",
        lambda s, e, index_type: _history_from_values("2024-01-01", [1500.0, 500.0]),
    )

    with pytest.raises(ValueError, match="data_unavailable"):
        service._build_valid_fallback_history(start, end, "TOPIX")
