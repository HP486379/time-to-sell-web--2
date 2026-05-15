import os
import sys
import json
from datetime import date

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from fastapi import HTTPException
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
        preloaded_price_history=None,
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
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: [("2024-01-01", 100.0), ("2024-01-02", 101.0)])
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


def test_backtest_insufficient_history_returns_structured_json_error(monkeypatch):
    def fake_run_backtest(*args, **kwargs):
        raise ValueError("insufficient_history_for_requested_start:requested_start=2004-01-01,first_available=2014-01-01")

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("insufficient_history_for_requested_start:requested_start=2004-01-01,first_available=2014-01-01")))
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2005-01-01",
        end_date="2025-12-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["error"] == "insufficient_history_for_requested_start"
    assert excinfo.value.detail["requested_start_date"] == "2004-01-01"
    assert excinfo.value.detail["available_start_date"] == "2014-01-01"


def test_backtest_fetch_timeout_returns_structured_json_error(monkeypatch):
    def fake_run_backtest(*args, **kwargs):
        raise ValueError("price_history_fetch_timeout:index_type=SP500,requested_start=2004-01-01,end_date=2025-12-31")

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("price_history_fetch_timeout:index_type=SP500,requested_start=2004-01-01,end_date=2025-12-31")))
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2005-01-01",
        end_date="2025-12-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 504
    assert excinfo.value.detail["error"] == "price_history_fetch_timeout"


def test_backtest_exec_timeout_returns_structured_json_error(monkeypatch):
    def fake_run_backtest(*args, **kwargs):
        import time
        time.sleep(0.2)
        return {}

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: [("2004-01-01", 100.0)])
    monkeypatch.setenv("BACKTEST_EXEC_TIMEOUT_SEC", "0.01")
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2005-01-01",
        end_date="2025-12-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 504
    assert excinfo.value.detail["error"] == "backtest_timeout"
    assert "precomputed_lookup_key" in excinfo.value.detail
    assert "precomputed_expected_path" in excinfo.value.detail
    assert "precomputed_file_exists" in excinfo.value.detail
    assert "precomputed_hit" in excinfo.value.detail
    assert "precomputed_miss_reason" in excinfo.value.detail
    assert isinstance(excinfo.value.detail["precomputed_file_exists"], bool)
    assert isinstance(excinfo.value.detail["precomputed_hit"], bool)


def test_backtest_data_unavailable_returns_structured_json_error(monkeypatch):
    def fake_run_backtest(*args, **kwargs):
        raise ValueError("data_unavailable")

    class _Market:
        def get_last_debug(self, index_type):
            return {"provider_attempts": [{"provider": "yfinance", "symbol": "^GSPC"}]}

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("data_unavailable")))
    monkeypatch.setattr(main.backtest_service, "market_service", _Market(), raising=False)
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2005-01-01",
        end_date="2025-12-31",
        initial_cash=100000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 503
    assert excinfo.value.detail["error"] == "price_history_data_unavailable"
    assert excinfo.value.detail["provider"] == "yfinance"
    assert excinfo.value.detail["symbol"] == "^GSPC"


def test_backtest_returns_precomputed_when_request_matches(tmp_path, monkeypatch):
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2004-01-01",
        end_date="2025-12-31",
        initial_cash=1000000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    key = "SP500|2004-01-01|2025-12-31|1000000.00|40.00|80.00|200"
    doc = {
        "precomputed_key": key,
        "generated_at": "2026-05-13T00:00:00Z",
        "logic_version": "v1",
        "result": {
            "final_value": 111111.0,
            "buy_and_hold_final": 100000.0,
            "total_return_pct": 11.11,
            "max_drawdown_pct": 9.99,
            "trade_count": 3,
            "price_history": [["2004-01-01", 100.0], ["2025-12-31", 111.11]],
            "diagnostics": {"trade_summary": {"trade_count": 3}},
        },
    }
    f = tmp_path / "sp500_2004-01-01_2025-12-31_sell80_buy40_ma200.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(main, "PRECOMPUTED_BACKTEST_DIR", tmp_path)
    response = main.run_backtest(payload)
    body = response.model_dump()
    assert body["summary"]["final_equity"] == 111111.0
    assert body["diagnostics"]["result_source"] == "precomputed"
    assert body["diagnostics"]["precomputed_key"] == key


def test_backtest_returns_precomputed_for_sp500_jpy_when_file_exists(tmp_path, monkeypatch):
    payload = BacktestRequest(
        index_type="SP500_JPY",
        start_date="2004-01-01",
        end_date="2025-12-31",
        initial_cash=1000000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    key = "SP500_JPY|2004-01-01|2025-12-31|1000000.00|40.00|80.00|200"
    doc = {
        "precomputed_key": key,
        "generated_at": "2026-05-13T00:00:00Z",
        "logic_version": "v1",
        "result": {
            "final_value": 2222222.0,
            "buy_and_hold_final": 2000000.0,
            "total_return_pct": 122.22,
            "max_drawdown_pct": 10.0,
            "trade_count": 4,
            "price_history": [["2004-01-01", 100.0], ["2025-12-31", 222.22]],
            "diagnostics": {"trade_summary": {"trade_count": 4}},
        },
    }
    f = tmp_path / "sp500_jpy_2004-01-01_2025-12-31_sell80_buy40_ma200.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(main, "PRECOMPUTED_BACKTEST_DIR", tmp_path)
    response = main.run_backtest(payload)
    body = response.model_dump()
    assert body["summary"]["final_equity"] == 2222222.0
    assert body["diagnostics"]["result_source"] == "precomputed"


def test_backtest_precomputed_key_mismatch_falls_back_to_runtime(tmp_path, monkeypatch):
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2004-01-01",
        end_date="2025-12-31",
        initial_cash=1000000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
        debug=True,
    )
    doc = {
        "precomputed_key": "SP500|2004-01-01|2025-12-31|999999.00|40.00|80.00|200",
        "generated_at": "2026-05-13T00:00:00Z",
        "logic_version": "v1",
        "result": {
            "final_value": 111111.0,
            "buy_and_hold_final": 100000.0,
            "total_return_pct": 11.11,
            "max_drawdown_pct": 9.99,
            "trade_count": 3,
            "price_history": [["2004-01-01", 100.0], ["2025-12-31", 111.11]],
            "diagnostics": {"trade_summary": {"trade_count": 3}},
        },
    }
    f = tmp_path / "sp500_2004-01-01_2025-12-31_sell80_buy40_ma200.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(main, "PRECOMPUTED_BACKTEST_DIR", tmp_path)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("insufficient_history_for_requested_start:requested_start=2004-01-01,first_available=2014-01-01")))
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["precomputed_hit"] is False
    assert excinfo.value.detail["precomputed_miss_reason"] == "key_mismatch"


def test_backtest_precomputed_key_mismatch_when_buy_sell_order_is_swapped(tmp_path, monkeypatch):
    payload = BacktestRequest(
        index_type="SP500",
        start_date="2004-01-01",
        end_date="2025-12-31",
        initial_cash=1000000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
        debug=True,
    )
    # buy/sell order swapped inside stored key on purpose
    doc = {
        "precomputed_key": "SP500|2004-01-01|2025-12-31|1000000.00|80.00|40.00|200",
        "generated_at": "2026-05-13T00:00:00Z",
        "logic_version": "v1",
        "result": {
            "final_value": 111111.0,
            "buy_and_hold_final": 100000.0,
            "total_return_pct": 11.11,
            "max_drawdown_pct": 9.99,
            "trade_count": 3,
            "price_history": [["2004-01-01", 100.0], ["2025-12-31", 111.11]],
            "diagnostics": {"trade_summary": {"trade_count": 3}},
        },
    }
    f = tmp_path / "sp500_2004-01-01_2025-12-31_sell80_buy40_ma200.json"
    f.write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(main, "PRECOMPUTED_BACKTEST_DIR", tmp_path)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: (_ for _ in ()).throw(ValueError("insufficient_history_for_requested_start:requested_start=2004-01-01,first_available=2014-01-01")))
    with pytest.raises(HTTPException) as excinfo:
        main.run_backtest(payload)
    assert excinfo.value.status_code == 400
    assert excinfo.value.detail["precomputed_hit"] is False
    assert excinfo.value.detail["precomputed_miss_reason"] == "key_mismatch"

def test_backtest_falls_back_to_runtime_when_precomputed_not_matched(monkeypatch):
    def fake_run_backtest(*args, **kwargs):
        return {
            "final_value": 123.0,
            "buy_and_hold_final": 120.0,
            "total_return_pct": 3.0,
            "max_drawdown_pct": 1.0,
            "trade_count": 1,
            "price_history": [("2024-01-01", 100.0), ("2024-01-02", 101.0)],
            "diagnostics": {"trade_summary": {"trade_count": 1}},
        }

    monkeypatch.setattr(main.backtest_service, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", lambda *args, **kwargs: [("2024-01-01", 100.0), ("2024-01-02", 101.0)])
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
    assert body["summary"]["final_equity"] == 123.0
    assert body["diagnostics"].get("result_source") != "precomputed"


@pytest.mark.parametrize(
    "index_type,filename,key",
    [
        ("TOPIX", "topix_2004-01-01_2025-12-31_sell80_buy40_ma200.json", "TOPIX|2004-01-01|2025-12-31|1000000.00|40.00|80.00|200"),
        ("ALLCOUNTRY_JPY", "allcountry_jpy_2004-01-01_2025-12-31_sell80_buy40_ma200.json", "ALLCOUNTRY_JPY|2004-01-01|2025-12-31|1000000.00|40.00|80.00|200"),
        ("NIFTY50", "nifty50_2004-01-01_2025-12-31_sell80_buy40_ma200.json", "NIFTY50|2004-01-01|2025-12-31|1000000.00|40.00|80.00|200"),
    ],
)
def test_backtest_precomputed_short_circuits_before_history_validation_for_2004_requests(
    tmp_path, monkeypatch, index_type, filename, key
):
    payload = BacktestRequest(
        index_type=index_type,
        start_date="2004-01-01",
        end_date="2025-12-31",
        initial_cash=1000000,
        buy_threshold=40,
        sell_threshold=80,
        score_ma=200,
    )
    doc = {
        "precomputed_key": key,
        "generated_at": "2026-05-15T00:00:00Z",
        "logic_version": "v1",
        "result": {
            "final_value": 1500000.0,
            "buy_and_hold_final": 1400000.0,
            "total_return_pct": 50.0,
            "max_drawdown_pct": 20.0,
            "trade_count": 5,
            "price_history": [["2004-01-01", 100.0], ["2025-12-31", 150.0]],
            "diagnostics": {"trade_summary": {"trade_count": 5}},
        },
    }
    (tmp_path / filename).write_text(json.dumps(doc), encoding="utf-8")
    monkeypatch.setattr(main, "PRECOMPUTED_BACKTEST_DIR", tmp_path)

    def fail_if_called(*args, **kwargs):
        raise AssertionError("fetch_and_validate_price_history_for_backtest should not be called on precomputed hit")

    monkeypatch.setattr(main.backtest_service, "fetch_and_validate_price_history_for_backtest", fail_if_called)

    response = main.run_backtest(payload)
    body = response.model_dump()
    assert body["diagnostics"]["result_source"] == "precomputed"
    assert body["diagnostics"]["precomputed_key"] == key
