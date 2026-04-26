import os
import sys
from datetime import date

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
from main import BacktestRequest


def test_backtest_response_contains_legacy_and_current_keys(monkeypatch):
    def fake_run_backtest(
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float,
        sell_threshold: float,
        index_type: str,
        score_ma: int,
    ):
        return {
            "final_value": 123456.78,
            "buy_and_hold_final": 120000.12,
            "total_return_pct": 23.45,
            "cagr_pct": 2.34,
            "max_drawdown_pct": 10.5,
            "trade_count": 7,
            "trades": [],
            "portfolio_history": [],
            "buy_hold_history": [],
            "price_history": [("2024-01-01", 100.0), ("2024-01-02", 101.0)],
            "diagnostics": {
                "trade_summary": {"trade_count": 7},
                "initial_entry": {"starts_invested": True},
                "initial_position": {"starts_invested": True, "initial_position_is_trade": False},
                "exposure": {"total_trading_days": 2},
            },
        }

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2024-01-01",
        end_date="2024-01-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    response = main.run_backtest(payload)
    body = response.model_dump()

    # 現行キー（web）
    assert body["summary"]["final_equity"] == 123456.78
    assert body["summary"]["hold_equity"] == 120000.12
    # 旧キー（iOS想定）
    assert body["summary"]["final_asset"] == 123456.78
    assert body["summary"]["buy_and_hold_asset"] == 120000.12
    # flat互換（iOS想定）
    assert body["final_asset"] == 123456.78
    assert body["buy_and_hold_asset"] == 120000.12
    assert body["total_return"] == 23.45
    assert body["max_drawdown"] == 10.5
    assert body["trade_count"] == 7
    assert "diagnostics" in body
    assert "trade_summary" in body["diagnostics"]
    assert "initial_entry" in body["diagnostics"]
    assert "initial_position" in body["diagnostics"]
    assert "exposure" in body["diagnostics"]
