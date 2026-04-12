import backend.main as main
import pytest


def test_sp500_price_history_builds_response(monkeypatch):
    monkeypatch.setattr(
        main.market_service,
        "get_price_history",
        lambda *args, **kwargs: [("2024-01-01", 100.0), ("2024-01-02", 101.0)],
    )
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *args, **kwargs: "real")
    monkeypatch.setattr(
        main.market_service,
        "build_price_series_with_ma",
        lambda history: [{"date": d, "close": c, "ma20": None, "ma60": None} for d, c in history],
    )

    payload = main._get_price_series_or_503(main.IndexType.SP500)
    assert len(payload) == 2
    assert payload[-1]["close"] == 101.0


def test_scoring_guard_rejects_last_good_without_freshness(monkeypatch):
    monkeypatch.setattr(main.market_service, "get_last_debug", lambda *_: {"source": "last_good", "adopted_provider": "last_good"})
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *_: "last_good")
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.SP500, [])
    assert ok is False
    assert "source_scoring_disabled" in reason


def test_scoring_guard_accepts_success_provider(monkeypatch):
    monkeypatch.setattr(main.market_service, "get_last_debug", lambda *_: {"source": "real", "adopted_provider": "yfinance"})
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *_: "real")
    ok, reason = main._is_debug_eligible_for_scoring(
        main.IndexType.SP500,
        [("2024-01-01", 100.0), ("2024-01-02", 101.0)],
    )
    assert ok is True
    assert reason == "series_ok"


def test_scoring_guard_allows_topix_close_fallback_warning(monkeypatch):
    monkeypatch.setattr(main.market_service, "get_last_debug", lambda *_: {"source": "real", "adopted_provider": "yfinance"})
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *_: "real")
    ok, reason = main._is_debug_eligible_for_scoring(
        main.IndexType.TOPIX,
        [("2024-01-01", 1900.0), ("2024-01-02", 1910.0), ("2024-01-03", 1905.0)],
    )
    assert ok is True
    assert reason == "series_ok"


def test_scoring_guard_rejects_topix_scale_switch():
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(main.market_service, "get_last_debug", lambda *_: {"source": "real", "adopted_provider": "yfinance"})
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *_: "real")
    series = [("2024-01-01", 2000.0 + i) for i in range(80)]
    series += [("2024-03-22", 200.0), ("2024-03-23", 210.0), ("2024-03-24", 220.0), ("2024-03-25", 230.0), ("2024-03-26", 240.0)]
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.TOPIX, series)
    assert ok is False
    assert "topix" in reason
    monkeypatch.undo()


def test_scoring_guard_rejects_synthetic_fallback_source(monkeypatch):
    monkeypatch.setattr(main.market_service, "get_last_debug", lambda *_: {"source": "synthetic_fallback", "adopted_provider": "synthetic_fallback"})
    monkeypatch.setattr(main.market_service, "get_last_source", lambda *_: "synthetic_fallback")
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.TOPIX, [("2024-01-01", 1500.0), ("2024-01-02", 1501.0)])
    assert ok is False
    assert "synthetic_fallback_scoring_disabled" == reason
