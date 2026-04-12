import backend.main as main


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
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.SP500, [])
    assert ok is False
    assert "series_empty" in reason


def test_scoring_guard_accepts_success_provider(monkeypatch):
    ok, reason = main._is_debug_eligible_for_scoring(
        main.IndexType.SP500,
        [("2024-01-01", 100.0), ("2024-01-02", 101.0)],
    )
    assert ok is True
    assert reason == "series_ok"


def test_scoring_guard_allows_topix_close_fallback_warning(monkeypatch):
    ok, reason = main._is_debug_eligible_for_scoring(
        main.IndexType.TOPIX,
        [("2024-01-01", 1900.0), ("2024-01-02", 1910.0), ("2024-01-03", 1905.0)],
    )
    assert ok is True
    assert reason == "series_ok"
