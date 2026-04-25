from datetime import date, timedelta
import os
import sys
import math
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.backtest_service import BacktestService


class FakeMarketService:
    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        history = []
        for i in range(250):
            dt = start + timedelta(days=i)
            price = 100.0 if i < 230 else 200.0
            history.append((dt.isoformat(), price))
        return history


class FakeMacroService:
    def get_macro_series_range(self, start: date, end: date):
        series = []
        days = (end - start).days
        for i in range(days + 1):
            dt = start + timedelta(days=i)
            value = 0.0 if i < 230 else 10.0
            series.append((dt, value))
        return {"r_10y": series, "cpi": series, "vix": series}


class FakeEventService:
    def get_events_for_date(self, target: date):
        return []


def test_backtest_generates_buy_and_sell_cycle():
    start = date(2020, 1, 1)
    end = start + timedelta(days=249)
    service = BacktestService(FakeMarketService(), FakeMacroService(), FakeEventService())

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    assert result["trade_count"] == 1
    assert result["trades"][0]["action"] == "BUY"
    # sell gateにより、score条件のみではSELLしない
    assert result["diagnostics"]["sell_gate_block_count"] > 0
    assert "buy_reason_counts" in result["diagnostics"]
    assert "pattern_a" in result["diagnostics"]["buy_reason_counts"]
    assert "pattern_b" in result["diagnostics"]["buy_reason_counts"]
    assert "both" in result["diagnostics"]["buy_reason_counts"]
    assert "day60" in result["diagnostics"]["buy_reason_counts"]
    assert "early_buy_ratio_pct" in result["diagnostics"]
    assert "avg_cash_wait_days" in result["diagnostics"]
    # 新BUYゲートでは回復確認後に遅れてエントリーするため、
    # 最終日に近い買い付けとなるケースでは初期資金と同水準に留まる
    assert result["final_value"] >= 1000.0
    assert result["buy_and_hold_final"] >= 2000.0


class FakeMarketServiceWithInvalidRows:
    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        history = []
        for i in range(260):
            dt = start + timedelta(days=i)
            price = 100.0 + i
            history.append((dt.isoformat(), price))
        history[10] = (history[10][0], float("nan"))
        history[20] = (history[20][0], "123.45")
        history[30] = ("invalid-date", 150.0)
        return history


def test_backtest_sanitizes_invalid_price_rows():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    service = BacktestService(FakeMarketServiceWithInvalidRows(), FakeMacroService(), FakeEventService())

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    assert math.isfinite(result["final_value"])
    assert math.isfinite(result["buy_and_hold_final"])
    assert math.isfinite(result["total_return_pct"])
    assert math.isfinite(result["max_drawdown_pct"])
    assert all(math.isfinite(v) for _, v in result["price_history"])


class BacktestServiceWithNaNScore(BacktestService):
    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        return float("nan")


def test_backtest_raises_when_score_becomes_nan():
    start = date(2020, 1, 1)
    end = start + timedelta(days=249)
    service = BacktestServiceWithNaNScore(FakeMarketService(), FakeMacroService(), FakeEventService())

    with pytest.raises(ValueError, match="invalid_score:non_finite"):
        service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")
