import os
import sys
from datetime import date

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main
from main import BacktestRequest, BacktestDiagnosticsSummaryRequest


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


def test_backtest_diagnostics_summary_contains_all_target_indexes(monkeypatch):
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
            "final_value": 1100.0,
            "buy_and_hold_final": 1000.0,
            "trade_count": 2,
            "diagnostics": {
                "score_max": 88.8,
                "sell_threshold_hit_days": 12,
                "sell_signal_count": 1,
                "trade_summary": {"buy_count": 1, "sell_count": 1},
                "sell_events": [
                    {
                        "date": "2024-01-10",
                        "sell_reason": ["sell_gate_open", "cooldown_clear"],
                        "return_until_buyback_pct": 1.23,
                        "post_return_20d_pct": -0.5,
                    }
                ],
                "buy_events": [
                    {
                        "date": "2024-01-20",
                        "buy_reason": ["buy_gate_open", "day60"],
                    }
                ],
            },
        }

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)

    payload = BacktestDiagnosticsSummaryRequest(
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    response = main.run_backtest_diagnostics_summary(payload)
    body = response.model_dump()

    assert "results" in body
    assert "errors" in body
    assert len(body["errors"]) == 0
    assert len(body["results"]) == 7
    item = body["results"][0]
    assert item["final_equity"] == 1100.0
    assert item["hold_equity"] == 1000.0
    assert item["diff_amount"] == 100.0
    assert item["diff_pct"] == 10.0
    assert item["trade_count"] == 2
    assert item["buy_count"] == 1
    assert item["sell_count"] == 1
    assert item["sell_dates"] == ["2024-01-10"]
    assert item["buy_dates"] == ["2024-01-20"]
    assert "sell_gate_open" in item["sell_reasons"]
    assert "buy_gate_open" in item["buy_reasons"]
    assert item["return_until_buyback_pct"] == [1.23]
    assert item["post_return_20d_pct"] == [-0.5]
    assert item["max_score"] == 88.8
    assert item["sell_threshold_hit_days"] == 12
    assert item["sell_signal_count"] == 1


def test_backtest_diagnostics_summary_respects_index_types_filter(monkeypatch):
    called_indexes = []

    def fake_run_backtest(
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float,
        sell_threshold: float,
        index_type: str,
        score_ma: int,
    ):
        called_indexes.append(index_type)
        return {
            "final_value": 1100.0,
            "buy_and_hold_final": 1000.0,
            "trade_count": 0,
            "diagnostics": {
                "score_max": 80.0,
                "sell_threshold_hit_days": 0,
                "sell_signal_count": 0,
                "trade_summary": {"buy_count": 0, "sell_count": 0},
                "sell_events": [],
                "buy_events": [],
            },
        }

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)

    payload = BacktestDiagnosticsSummaryRequest(
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_cash=100000,
        index_types=["SP500", "NIKKEI225"],
    )
    response = main.run_backtest_diagnostics_summary(payload)
    body = response.model_dump()

    assert called_indexes == ["SP500", "NIKKEI225"]
    assert [item["index_type"] for item in body["results"]] == ["SP500", "NIKKEI225"]
    assert body["errors"] == []


def test_backtest_diagnostics_summary_returns_partial_results_with_errors(monkeypatch):
    def fake_run_backtest(
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float,
        sell_threshold: float,
        index_type: str,
        score_ma: int,
    ):
        if index_type == "ALLCOUNTRY_JPY":
            raise ValueError("mock timeout or data unavailable")
        return {
            "final_value": 1100.0,
            "buy_and_hold_final": 1000.0,
            "trade_count": 0,
            "diagnostics": {
                "score_max": 80.0,
                "sell_threshold_hit_days": 0,
                "sell_signal_count": 0,
                "trade_summary": {"buy_count": 0, "sell_count": 0},
                "sell_events": [],
                "buy_events": [],
            },
        }

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)

    payload = BacktestDiagnosticsSummaryRequest(
        start_date="2024-01-01",
        end_date="2024-12-31",
        initial_cash=100000,
    )
    response = main.run_backtest_diagnostics_summary(payload)
    body = response.model_dump()

    assert len(body["results"]) == 6
    assert len(body["errors"]) == 1
    assert body["errors"][0]["index_type"] == "ALLCOUNTRY_JPY"
    assert "mock timeout or data unavailable" in body["errors"][0]["error"]
