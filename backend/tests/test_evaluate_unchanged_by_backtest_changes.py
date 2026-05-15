import os, sys
from types import SimpleNamespace

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import asyncio
import pytest
import main


@pytest.mark.parametrize("index_type", ["SP500", "TOPIX", "NIKKEI225", "ALLCOUNTRY_JPY"])
def test_evaluate_not_using_precomputed_backtest_path(monkeypatch, index_type):
    async def fake_resolve_debug_flag(request, query_debug):
        return False

    def fake_get_cached_snapshot(position_index_type, allow_synthetic=False, allow_low_quality=False):
        return {
            "status": "ok",
            "source": "market_data",
            "adopted_provider": "unit-test",
            "scores": {
                "technical": 71.2,
                "macro": 62.5,
                "event_adjustment": 1.0,
                "total": 68.4,
                "label": "HOLD",
            },
            "sell_recommendation": {"action": "HOLD"},
            "price_history": [["2026-01-01", 100.0], ["2026-01-02", 101.0]],
            "price_series": [],
        }

    def fail_if_called(*args, **kwargs):
        raise AssertionError("_load_precomputed_backtest must not be used by /api/evaluate")

    monkeypatch.setattr(main, "_resolve_debug_flag", fake_resolve_debug_flag)
    monkeypatch.setattr(main, "get_cached_snapshot", fake_get_cached_snapshot)
    monkeypatch.setattr(main, "_load_precomputed_backtest", fail_if_called)

    position = main.PositionRequest(index_type=index_type)
    response = asyncio.run(main.evaluate(SimpleNamespace(query_params={}, json=lambda: {}), position))

    assert response["scores"]["total"] == 68.4
    assert response["scores"]["technical"] == 71.2
    assert response["scores"]["macro"] == 62.5
    assert response["scores"]["event_adjustment"] == 1.0
    assert response["scores"]["label"] == "HOLD"
    assert response["sell_recommendation"]["action"] == "HOLD"
