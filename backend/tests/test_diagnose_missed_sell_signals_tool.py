from datetime import date

from tools.diagnose_missed_sell_signals import diagnose_index, parse_index_types, run_diagnosis


class _MarketService:
    def get_price_history_range(self, start, end, allow_fallback, index_type):
        prices = []
        for i in range(320):
            dt = start.fromordinal(start.toordinal() + i)
            if i < 230:
                px = 100.0
            elif i < 250:
                px = 90.0
            else:
                px = 85.0
            prices.append((dt.isoformat(), px))
        return prices


class _MacroService:
    def get_macro_series_range(self, start, end):
        vals = []
        for i in range((end - start).days + 1):
            dt = start.fromordinal(start.toordinal() + i)
            vals.append((dt, 0.0))
        return {"r_10y": vals, "cpi": vals, "vix": vals}


class _BacktestService:
    allow_fallback = False
    market_service = _MarketService()
    macro_service = _MacroService()
    event_service = type("_EventSvc", (), {"get_events_for_date": lambda self, d: []})()

    def _prepare_price_history(self, raw_history, index_type):
        return raw_history

    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        return 70.0

    def _history_and_current(self, series, current_date):
        vals = [v for d, v in series if d <= current_date]
        if len(vals) <= 1:
            return [0.0], 0.0
        return vals[:-1], vals[-1]


class _Ctx:
    backtest_service = _BacktestService()


def test_parse_index_types():
    assert parse_index_types(None)[0] == "SP500"
    assert "ALLCOUNTRY_JPY" in parse_index_types(None)
    assert parse_index_types("SP500,TOPIX") == ["SP500", "TOPIX"]


def test_diagnose_index_returns_detail_and_summary(monkeypatch):
    monkeypatch.setattr(
        "tools.diagnose_missed_sell_signals.calculate_technical_score",
        lambda history, base_window=200: (50.0, {}),
    )
    result = diagnose_index(
        _Ctx(),
        index_type="SP500",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        score_ma=200,
    )

    assert "summary" in result
    assert "details" in result
    assert result["summary"]["index_type"] == "SP500"
    assert result["summary"]["large_drop_candidate_count"] >= 1
    assert "technical_ge70_total_lt80_count" in result["summary"]
    assert "macro_drag_suspected_count" in result["summary"]
    assert "event_date_mismatch_count" in result["summary"]
    first = result["details"][0]
    assert "score_shortage_to_80" in first
    assert "sell_gate_open" in first
    assert "blockers" in first
    assert "technical_high_total_shortage" in first
    assert "macro_drag_suspected" in first
    assert "event_adjustment_is_zero" in first
    assert "event_adjustment_reason" in first
    assert "event_source_count" in first
    assert "nearby_events" in first
    assert "event_date_mismatch" in first
    assert "overheat_event_raw_conditions" in first
    assert "sell_gate_required_conditions" in first
    assert "sell_gate_failed_conditions" in first
    assert "overheat_event_active" in first
    assert "peakout_detected" in first
    assert "confirmation_detected" in first
    assert "case_tags" in first
    assert "max_drawdown_next_60d" in first


def test_run_diagnosis_multi_index(monkeypatch):
    monkeypatch.setattr(
        "tools.diagnose_missed_sell_signals.calculate_technical_score",
        lambda history, base_window=200: (50.0, {}),
    )
    payload = run_diagnosis(
        ctx=_Ctx(),
        indices=["SP500", "TOPIX"],
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        score_ma=200,
    )
    assert len(payload["summaries"]) == 2
    assert all("index_type" in x for x in payload["summaries"])


def test_nearby_events_are_candidate_date_based_and_reasons_vary(monkeypatch):
    class _EventService:
        def get_events_for_date(self, d):
            events = [
                {"date": "2026-04-29", "event": "FAR_A", "importance": 5},
                {"date": "2026-04-30", "event": "FAR_B", "importance": 4},
            ]
            if d.day % 2 == 0:
                events.append({"date": d.isoformat(), "event": "NEAR_TODAY", "importance": 5})
            return events

    class _BacktestWithEvents(_BacktestService):
        event_service = _EventService()

    class _CtxWithEvents:
        backtest_service = _BacktestWithEvents()

    monkeypatch.setattr(
        "tools.diagnose_missed_sell_signals.calculate_technical_score",
        lambda history, base_window=200: (50.0, {}),
    )
    result = diagnose_index(
        _CtxWithEvents(),
        index_type="SP500",
        start_date=date(2015, 1, 1),
        end_date=date(2015, 12, 31),
        initial_cash=1_000_000.0,
        score_ma=200,
    )
    assert result["summary"]["large_drop_candidate_count"] >= 1
    details = result["details"]
    assert any(d["event_adjustment_reason"] == "risk_weighted_penalty_applied" for d in details)
    assert any(d["event_adjustment_reason"] == "no_nearby_events" for d in details)
    assert len({d["event_source_count"] for d in details}) >= 2
    for d in details:
        for ev in d["nearby_events"]:
            assert not ev["event_date"].startswith("2026-04")
