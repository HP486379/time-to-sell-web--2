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
    monkeypatch.setattr(
        main.market_service,
        "get_last_debug",
        lambda *_: {
            "adopted_provider": "last_good",
            "fetch_error": None,
            "quality_check": {"result": "fallback_last_good", "reason": "provider_failed"},
            "last_good_freshness_ok": False,
            "last_good_quality_check": {"result": "failed", "reason": "stale_or_invalid_date"},
            "last_good_tail_check": {"result": "unknown", "reason": None},
        },
    )
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.SP500)
    assert ok is False
    assert "last_good_scoring_disabled" in reason


def test_scoring_guard_accepts_success_provider(monkeypatch):
    monkeypatch.setattr(
        main.market_service,
        "get_last_debug",
        lambda *_: {
            "adopted_provider": "yfinance",
            "fetch_error": None,
            "quality_check": {"result": "success", "reason": None},
        },
    )
    ok, reason = main._is_debug_eligible_for_scoring(main.IndexType.SP500)
    assert ok is True
    assert reason == "ok_provider"
