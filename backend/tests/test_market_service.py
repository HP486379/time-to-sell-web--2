import pandas as pd
import yfinance as yf
from datetime import date
import pytest

from backend.services.sp500_market_service import SP500MarketService
from backend.services.market_data_provider import YFinanceStructureError


def _history_from_values(start: str, values):
    dates = pd.date_range(start, periods=len(values), freq="B")
    return [(d.date().isoformat(), float(v)) for d, v in zip(dates, values)]


def _recent_history_from_values(values):
    end = pd.Timestamp.today().normalize()
    dates = pd.date_range(end=end, periods=len(values), freq="B")
    return [(d.date().isoformat(), float(v)) for d, v in zip(dates, values)]


def test_get_price_history_range_handles_dataframe(monkeypatch):
    service = SP500MarketService(symbol="TEST")

    dates = pd.date_range("2020-01-01", periods=35, freq="B")
    df = pd.DataFrame({"Close": [1000.0 + i for i in range(35)]}, index=dates)

    def fake_download(symbol, start, end, interval, **kwargs):  # pragma: no cover - simple stub
        return df

    monkeypatch.setattr(yf, "download", fake_download)
    monkeypatch.setattr(
        "services.market_data_provider._fetch_from_gateway",
        lambda provider, symbol, start, end: df["Close"],
    )

    history = service.get_price_history_range(dates[0].date(), dates[-1].date(), allow_fallback=False, index_type="TOPIX")
    assert history == [(d.date().isoformat(), float(1000.0 + i)) for i, d in enumerate(dates)]


def test_validate_history_rejects_abnormal_relative_scale():
    service = SP500MarketService(symbol="TEST")
    history = _history_from_values("2020-01-01", [4100.0] + [100.0 for _ in range(39)])

    reason = service._validate_history(history, "SP500")

    assert reason is not None
    assert "abnormal_ratio_low" in reason


def test_get_price_history_range_retries_and_recovers(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = pd.Timestamp("2020-01-01").date()
    end = pd.Timestamp("2020-03-31").date()

    abnormal = _history_from_values("2020-01-01", [4200.0] * 40 + [50000.0])
    normal = _history_from_values("2020-01-01", [4200.0 + i * 2 for i in range(41)])
    responses = [abnormal, normal]

    def fake_fetch(symbol, s, e, index_type=None):
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

    normal = _recent_history_from_values([4100.0 + i * 2 for i in range(260)])
    abnormal = _history_from_values("2020-01-01", [4100.0] * 40 + [50000.0])

    service._last_good_history["SP500"] = normal

    def always_bad(symbol, s, e, **kwargs):
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


def test_validate_history_soft_range_is_not_rejected():
    service = SP500MarketService(symbol="TEST")
    history = _history_from_values("2024-01-01", [100.0 + i * 10 for i in range(50)])

    reason = service._validate_history(history, "TOPIX")

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
    last_good = _recent_history_from_values([1500.0 + i for i in range(60)])
    service._last_good_history["SP500"] = last_good

    monkeypatch.setattr(
        service,
        "_fallback_history",
        lambda s, e, index_type: _history_from_values("2024-01-01", [1500.0, 100.0]),
    )

    history = service._build_valid_fallback_history(start, end, "SP500")
    assert history == last_good


def test_invalid_fallback_without_last_good_is_data_unavailable(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)

    monkeypatch.setattr(
        service,
        "_fallback_history",
        lambda s, e, index_type: _history_from_values("2024-01-01", [1500.0, 100.0]),
    )

    with pytest.raises(ValueError, match="data_unavailable"):
        service._build_valid_fallback_history(start, end, "SP500")


def test_topix_fallback_skips_strict_quality_gate(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    degraded = _history_from_values("2024-01-01", [1500.0, 100.0])

    monkeypatch.setattr(service, "_fallback_history", lambda s, e, index_type: degraded)

    history = service._build_valid_fallback_history(start, end, "TOPIX")
    assert history == degraded


def test_last_good_source_marked_as_last_good(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    last_good = _recent_history_from_values([4100.0 + i for i in range(260)])
    service._last_good_history["SP500"] = last_good

    monkeypatch.setattr(service, "_download_close_series", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fail")))
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=False, index_type="SP500")
    assert history == last_good
    assert service.get_last_source("SP500") == "last_good"


def test_topix_symbol_candidates_include_fallback():
    service = SP500MarketService(symbol="TEST")
    candidates = service._resolve_symbol_candidates("TOPIX")
    assert "^TOPX" in candidates
    assert len(candidates) == 1


def test_topix_tail_outlier_is_relaxed():
    service = SP500MarketService(symbol="TEST")
    base = [100.0 for _ in range(219)]
    prev_window = [105.0 for _ in range(19)] + [120.0]
    topix_history = _history_from_values("2024-01-01", base + prev_window + [138.0])
    sp500_history = _history_from_values("2024-01-01", base + prev_window + [138.0])

    topix_reason = service._provider_acceptance_reason(topix_history, "TOPIX")
    sp500_reason = service._provider_acceptance_reason(sp500_history, "SP500")

    assert topix_reason is None
    assert sp500_reason is not None
    assert "tail_outlier" in sp500_reason


def test_topix_uses_stooq_index_provider(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 12, 31)
    points = _history_from_values("2024-01-01", [2000.0 + i for i in range(260)])

    dates = pd.to_datetime([d for d, _ in points])
    values = [v for _, v in points]
    monkeypatch.setattr("backend.services.sp500_market_service.fetch_history_from_stooq", lambda *args, **kwargs: pd.Series(values, index=dates))

    history = service.get_price_history_range(start, end, allow_fallback=True, index_type="TOPIX")
    debug = service.get_last_debug("TOPIX")

    assert history == points
    assert debug.get("adopted_provider") == "stooq"
    assert debug.get("adopted_symbol") == "TOPIX"
    assert debug.get("resolved_symbol") == "TOPIX"
    assert debug.get("index_mode") == "index"


def test_topix_returns_fallback_without_quality_rejection(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    degraded = _history_from_values("2024-01-01", [1500.0, 500.0])

    monkeypatch.setattr(service, "_download_close_series", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fail")))
    monkeypatch.setattr(service, "_fallback_history", lambda s, e, index_type: degraded)
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=True, index_type="TOPIX")

    assert history == degraded
    assert service.get_last_source("TOPIX") == "fallback"

def test_topix_returns_fallback_when_yfinance_fails(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    fallback = _history_from_values("2024-01-01", [1500.0 + i for i in range(40)])

    monkeypatch.setattr("backend.services.sp500_market_service.fetch_history_from_stooq", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("403 blocked")))
    monkeypatch.setattr(service, "_build_valid_fallback_history", lambda s, e, index_type: fallback)
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=True, index_type="TOPIX")
    debug = service.get_last_debug("TOPIX")
    assert history == fallback
    assert debug.get("resolved_symbol") == "TOPIX"
    assert debug.get("index_mode") == "index"
    assert service.get_last_source("TOPIX") == "fallback"
    assert "stooq:TOPIX:403_blocked" in (debug.get("provider_reject_reasons") or [])


def test_topix_sets_empty_dataframe_fetch_error(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    monkeypatch.setattr("backend.services.sp500_market_service.fetch_history_from_stooq", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("empty dataframe")))
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    with pytest.raises(ValueError, match="data_unavailable"):
        service._fetch_topix_with_provider_priority(start, end)
    debug = service.get_last_debug("TOPIX")
    assert debug.get("fetch_error") == "empty_dataframe"


def test_debug_has_provider_attempt_fields(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    ok = _history_from_values("2024-01-01", [2000.0 + i for i in range(260)])

    def fake_stooq(*args, **kwargs):
        dates = pd.to_datetime([d for d, _ in ok])
        values = [v for _, v in ok]
        return pd.Series(values, index=dates)

    monkeypatch.setattr("backend.services.sp500_market_service.fetch_history_from_stooq", fake_stooq)
    history = service.get_price_history_range(start, end, allow_fallback=False, index_type="TOPIX")

    debug = service.get_last_debug("TOPIX")
    attempts = debug.get("provider_attempts")
    assert history == ok
    assert isinstance(attempts, list)
    assert attempts
    for attempt in attempts:
        assert "provider" in attempt
        assert "success" in attempt
        assert "first_close" in attempt
        assert "last_close" in attempt
        assert "ratio" in attempt
        assert "validation_passed" in attempt
        assert "reject_reason" in attempt
    assert isinstance(debug.get("provider_reject_reasons"), list)


def test_topix_debug_includes_required_normalization_fields(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    idx = pd.to_datetime(["2024-01-04", "2024-01-05"])
    series = pd.Series([390.0, 400.0], index=idx)
    raw_meta = {
        "raw_head_ohlcv": [{"Date": "2024-01-04", "Close": "1800", "Adj Close": "390"}],
        "raw_tail_ohlcv": [{"Date": "2024-01-05", "Close": "400", "Adj Close": "400"}],
        "column_names": ["Open", "High", "Low", "Close", "Adj Close", "Volume"],
        "selected_price_column": "Adj Close",
        "used_adjusted_close": True,
        "source_path": "direct",
        "raw_is_ascending": True,
        "raw_is_descending": False,
        "split_column_present": False,
        "auto_adjust": False,
        "raw_close_head5": [1800.0],
        "raw_close_tail10": [400.0],
        "raw_adj_close_head5": [390.0],
        "raw_adj_close_tail10": [400.0],
    }
    monkeypatch.setattr(
        "backend.services.sp500_market_service.fetch_history_from_yfinance_with_debug",
        lambda *args, **kwargs: (series, raw_meta),
    )

    result = service._download_close_series("^TOPX", start, end, "TOPIX")
    debug = service.get_last_debug("TOPIX")

    assert float(result.iloc[-1]) == 400.0
    assert debug.get("price_column_used") == "adj_close"
    assert debug.get("raw_close_tail") == [400.0]
    assert debug.get("raw_adj_close_tail") == [400.0]
    assert debug.get("normalized_series_tail") == [390.0, 400.0]
    assert debug.get("series_sort_order") == "asc"


def test_topix_debug_captures_raw_shape_on_column_error(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 1, 31)
    debug_meta = {
        "column_names": ["Open", "High"],
        "raw_shape": [0, 2],
        "raw_is_multiindex": True,
        "raw_head_ohlcv": [],
        "raw_tail_ohlcv": [],
    }
    monkeypatch.setattr(
        "backend.services.sp500_market_service.fetch_history_from_yfinance_with_debug",
        lambda *args, **kwargs: (_ for _ in ()).throw(YFinanceStructureError("close column missing", debug_meta=debug_meta)),
    )

    with pytest.raises(YFinanceStructureError):
        service._download_close_series("^TOPX", start, end, "TOPIX")

    debug = service.get_last_debug("TOPIX")
    assert debug.get("raw_columns") == ["Open", "High"]
    assert debug.get("raw_shape") == [0, 2]
    assert debug.get("raw_is_multiindex") is True


def test_provider_reject_reasons_is_reasonable_list(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    start = date(2024, 1, 1)
    end = date(2024, 3, 31)
    last_good = _recent_history_from_values([4100.0 + i for i in range(260)])
    service._last_good_history["SP500"] = last_good

    monkeypatch.setattr(service, "_download_close_series", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fail")))
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history_range(start, end, allow_fallback=False, index_type="SP500")
    debug = service.get_last_debug("SP500")

    assert history == last_good
    assert isinstance(debug.get("provider_reject_reasons"), list)


def test_stale_last_good_is_rejected(monkeypatch):
    service = SP500MarketService(symbol="TEST")
    service._last_good_history["SP500"] = _history_from_values("2020-01-01", [4100.0 + i for i in range(80)])
    monkeypatch.setattr(service, "_download_close_series", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("fail")))
    monkeypatch.setattr("backend.services.sp500_market_service.time.sleep", lambda *_: None)

    history = service.get_price_history(index_type="SP500", allow_synthetic=False)
    assert history

    debug = service.get_last_debug("SP500")
    assert debug.get("last_good_freshness_ok") is False
    assert service.get_last_source("SP500") in {"bootstrap", "synthetic", "fallback"}
