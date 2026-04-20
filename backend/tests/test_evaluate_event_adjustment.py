import os
import sys
from datetime import date

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main


def test_build_event_adjustment_uses_manual_events(monkeypatch):
    def fake_events_for_date(target: date):
        return [
            {"name": "ISM Manufacturing", "importance": 5, "date": target.isoformat(), "source": "manual"}
        ]

    monkeypatch.setattr(main.event_service, "get_events_for_date", fake_events_for_date)

    adj, details, count = main._build_event_adjustment(date(2026, 3, 2))

    assert -10.0 < adj < 0.0
    assert count == 1
    assert details["E_adj"] == adj
    assert details["effective_event"]["name"] == "ISM Manufacturing"


def test_evaluate_response_contains_event_adjustment_pt(monkeypatch):
    snapshot = {
        "current_price": 120.0,
        "scores": {"technical": 60.0, "macro": 10.0, "event_adjustment": 0.0, "total": 70.0, "label": "HOLD"},
        "technical_details": {"d": 1.0, "T_base": 50.0, "T_trend": 10.0},
        "macro_details": {"M": 10.0, "p_r": 1.0, "p_cpi": 1.0, "p_vix": 1.0},
        "event_details": {},
        "event_count": 0,
        "price_history": [("2026-03-01", 100.0), ("2026-03-02", 120.0)],
        "price_series": [
            {"date": "2026-03-01", "close": 100.0, "ma20": None, "ma60": None, "ma200": None},
            {"date": "2026-03-02", "close": 120.0, "ma20": 110.0, "ma60": None, "ma200": None},
        ],
    }

    monkeypatch.setattr(main, "get_cached_snapshot", lambda _index: snapshot)
    monkeypatch.setattr(main, "_build_event_adjustment", lambda _target: (-3.5, {"E_adj": -3.5}, 2))
    monkeypatch.setattr(
        main,
        "calculate_technical_score",
        lambda _history, base_window=200: (60.0, {"d": 1.0, "T_base": 50.0, "T_trend": 10.0}),
    )
    monkeypatch.setattr(main, "calculate_ultra_long_mas", lambda _history: (None, None))
    monkeypatch.setattr(
        main,
        "calculate_total_score",
        lambda technical, macro, event_adjustment, **_kwargs: technical + macro + event_adjustment,
    )

    payload = main.PositionRequest(total_quantity=10, avg_cost=100, index_type=main.IndexType.SP500, score_ma=200)
    result = main._evaluate(payload)

    assert result["event_adjustment_pt"] == -3.5
    assert result["event_count"] == 2
    assert result["scores"]["event_adjustment"] == -3.5
    assert result["scores"]["total"] == 72.5
