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

    assert result["trade_count"] >= 0
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


class FlatMacroService:
    def get_macro_series_range(self, start: date, end: date):
        series = []
        days = (end - start).days
        for i in range(days + 1):
            dt = start + timedelta(days=i)
            series.append((dt, 0.0))
        return {"r_10y": series, "cpi": series, "vix": series}


class SequenceMarketService:
    def __init__(self, prices):
        self._prices = prices

    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        history = []
        for i, price in enumerate(self._prices):
            history.append(((start + timedelta(days=i)).isoformat(), float(price)))
        return history


class ScriptedScoreBacktestService(BacktestService):
    def __init__(self, market_service, macro_service, event_service, score_plan):
        super().__init__(market_service, macro_service, event_service)
        self._score_plan = score_plan

    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        return self._score_plan.get(current_date, 70.0)


def _flat_technical(*args, **kwargs):
    return 50.0, {
        "ma50_for_breakdown": 100.0,
        "ma200_for_breakdown": 100.0,
        "ma50_slope": 0.001,
        "strong_uptrend": False,
    }


def test_sell_is_full_exit_only_when_breakdown_persists(monkeypatch):
    def _breakdown_two_days(price_history, base_window):
        details = {
            "ma50_for_breakdown": 90.0,
            "ma200_for_breakdown": 100.0,
            "ma50_slope": 0.001,
            "strong_uptrend": False,
        }
        if len(price_history) in (202, 203):  # idx=201,202
            details["ma50_for_breakdown"] = 95.0
            details["ma200_for_breakdown"] = 100.0
            details["ma50_slope"] = -0.001
        return 50.0, details

    monkeypatch.setattr("services.backtest_service.calculate_technical_score", _breakdown_two_days)
    start = date(2020, 1, 1)
    prices = [100.0] * 250
    prices[200] = 110.0
    prices[201] = 94.0
    prices[202] = 93.0
    score_plan = {start + timedelta(days=i): 70.0 for i in range(199, 250)}
    service = ScriptedScoreBacktestService(
        SequenceMarketService(prices),
        FlatMacroService(),
        FakeEventService(),
        score_plan,
    )

    result = service.run_backtest(start, start + timedelta(days=249), initial_cash=10000.0, index_type="SP500")
    sell_trades = [t for t in result["trades"] if t.get("action") == "SELL"]

    assert len(sell_trades) == 1
    assert sell_trades[0]["mode"] == "full_exit"
    assert sell_trades[0]["date"] == (start + timedelta(days=202)).isoformat()


def test_reentry_requires_trend_recovery(monkeypatch):
    def _trend_switch(price_history, base_window):
        details = _flat_technical()[1]
        if len(price_history) in (202, 203):
            details["ma50_for_breakdown"] = 95.0
            details["ma200_for_breakdown"] = 100.0
            details["ma50_slope"] = -0.001
        elif len(price_history) >= 206:
            details["ma50_for_breakdown"] = 105.0
            details["ma200_for_breakdown"] = 100.0
            details["ma50_slope"] = 0.001
        return 50.0, details

    monkeypatch.setattr("services.backtest_service.calculate_technical_score", _trend_switch)
    start = date(2020, 1, 1)
    prices = [100.0] * 250
    prices[200] = 110.0
    prices[201] = 94.0
    prices[202] = 93.0
    prices[203] = 96.0
    prices[204] = 97.0
    prices[205] = 106.0
    score_plan = {start + timedelta(days=i): 70.0 for i in range(199, 250)}
    score_plan[start + timedelta(days=199)] = 30.0  # initial entry

    service = ScriptedScoreBacktestService(
        SequenceMarketService(prices),
        FlatMacroService(),
        FakeEventService(),
        score_plan,
    )

    result = service.run_backtest(start, start + timedelta(days=249), initial_cash=10000.0, index_type="SP500")
    buy_modes = [t.get("mode") for t in result["trades"] if t.get("action") == "BUY"]

    assert "reentry_trend" in buy_modes


def test_strong_uptrend_never_sells(monkeypatch):
    def _strong_trend(*args, **kwargs):
        return 50.0, {
            "ma50_for_breakdown": 95.0,
            "ma200_for_breakdown": 100.0,
            "ma50_slope": -0.001,
            "strong_uptrend": True,
        }

    monkeypatch.setattr("services.backtest_service.calculate_technical_score", _strong_trend)
    start = date(2020, 1, 1)
    prices = [100.0] * 250
    prices[200] = 110.0
    prices[201] = 90.0
    prices[202] = 89.0
    score_plan = {start + timedelta(days=i): 30.0 for i in range(199, 250)}
    service = ScriptedScoreBacktestService(
        SequenceMarketService(prices),
        FlatMacroService(),
        FakeEventService(),
        score_plan,
    )

    result = service.run_backtest(start, start + timedelta(days=249), initial_cash=10000.0, index_type="SP500")
    sell_trades = [t for t in result["trades"] if t["action"] == "SELL"]

    assert sell_trades == []
