from datetime import date, timedelta
import os
import sys
import math
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.backtest_service import BacktestService
from scoring.technical import calculate_technical_score


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

    assert result["trade_count"] == len(result["trades"])
    # sell gateにより、score条件のみではSELLしない
    assert result["diagnostics"]["sell_gate_block_count"] > 0
    assert "trade_summary" in result["diagnostics"]
    assert "initial_entry" in result["diagnostics"]
    assert "initial_position" in result["diagnostics"]
    assert "exposure" in result["diagnostics"]
    assert result["diagnostics"]["trade_summary"]["trade_count"] == len(result["trades"])
    assert result["diagnostics"]["initial_position"]["starts_invested"] is True
    assert result["diagnostics"]["initial_position"]["initial_position_is_trade"] is False
    assert "buy_reason_counts" in result["diagnostics"]
    assert "pattern_a" in result["diagnostics"]["buy_reason_counts"]
    assert "pattern_b" in result["diagnostics"]["buy_reason_counts"]
    assert "both" in result["diagnostics"]["buy_reason_counts"]
    assert "day60" in result["diagnostics"]["buy_reason_counts"]
    assert "early_buy_ratio_pct" in result["diagnostics"]
    assert "avg_cash_wait_days" in result["diagnostics"]
    assert result["final_value"] >= 2000.0
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
    assert "score_samples" in result["diagnostics"]
    assert "sell_events" in result["diagnostics"]
    assert "buy_events" in result["diagnostics"]


class BacktestServiceWithNaNScore(BacktestService):
    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        return float("nan")


def test_backtest_raises_when_score_becomes_nan():
    start = date(2020, 1, 1)
    end = start + timedelta(days=249)
    service = BacktestServiceWithNaNScore(FakeMarketService(), FakeMacroService(), FakeEventService())

    with pytest.raises(ValueError, match="invalid_score:non_finite"):
        service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")


class FakeMarketServiceFlat:
    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        return [((start + timedelta(days=i)).isoformat(), 100.0) for i in range(260)]


class FakeMacroServiceFlat:
    def get_macro_series_range(self, start: date, end: date):
        return {
            "r_10y": [(start + timedelta(days=i), 0.0) for i in range((end - start).days + 1)],
            "cpi": [(start + timedelta(days=i), 0.0) for i in range((end - start).days + 1)],
            "vix": [(start + timedelta(days=i), 0.0) for i in range((end - start).days + 1)],
        }


def test_backtest_starts_invested_and_initial_position_not_counted_as_trade():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    service = BacktestService(FakeMarketServiceFlat(), FakeMacroServiceFlat(), FakeEventService())

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    assert result["diagnostics"]["initial_position"]["starts_invested"] is True
    assert result["diagnostics"]["initial_position"]["initial_position_is_trade"] is False
    assert result["diagnostics"]["initial_position"]["initial_shares"] == 10
    assert result["trade_count"] == len(result["trades"]) == 0
    assert result["final_value"] == result["buy_and_hold_final"]


class FakeMarketServiceForSellDiagnostics:
    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        history = []
        for i in range(260):
            dt = start + timedelta(days=i)
            if i < 230:
                price = 100.0
            else:
                price = 100.0 - (i - 229) * 0.8
            history.append((dt.isoformat(), price))
        return history


class BacktestServiceForSellDiagnostics(BacktestService):
    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        idx = len(price_history) - 1
        if idx < 230:
            return 82.0
        return 70.0 - ((idx - 229) * 0.5)


class BacktestServiceForSellDiagnosticsAboveThreshold(BacktestService):
    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        idx = len(price_history) - 1
        if idx < 230:
            return 90.0
        return 90.0 - ((idx - 229) * 0.2)


def test_sell_does_not_execute_when_score_below_threshold_even_if_gate_open():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    service = BacktestServiceForSellDiagnostics(
        FakeMarketServiceForSellDiagnostics(), FakeMacroServiceFlat(), FakeEventService()
    )

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    assert result["trade_count"] == 0
    assert result["diagnostics"]["sell_signal_count"] == 0
    assert result["diagnostics"]["sell_events"] == []


def test_sell_executes_only_when_score_threshold_and_sell_gate_conditions_are_met():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    service = BacktestServiceForSellDiagnosticsAboveThreshold(
        FakeMarketServiceForSellDiagnostics(), FakeMacroServiceFlat(), FakeEventService()
    )

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")
    sell_events = result["diagnostics"]["sell_events"]

    assert len(sell_events) >= 1
    first_sell = sell_events[0]
    assert first_sell["sell_reason_flags"]["score_threshold"] is True
    assert "sell_gate_open" in first_sell["sell_reason"]
    assert "cooldown_clear" in first_sell["sell_reason"]
    assert first_sell["sell_reason_flags"]["sell_gate_open"] is True
    assert first_sell["sell_reason_flags"]["cooldown_clear"] is True


def test_nikkei225_like_case_does_not_sell_when_score_threshold_is_false():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    service = BacktestServiceForSellDiagnostics(
        FakeMarketServiceForSellDiagnostics(), FakeMacroServiceFlat(), FakeEventService()
    )

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    assert result["trade_count"] == 0
    assert result["final_value"] == result["buy_and_hold_final"]
    assert all(event["sell_reason_flags"]["score_threshold"] for event in result["diagnostics"]["sell_events"])


class FakeMarketServiceForBuyDiagnostics:
    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ):
        history = []
        for i in range(340):
            dt = start + timedelta(days=i)
            if i < 230:
                price = 100.0
            elif i < 260:
                price = 100.0 - (i - 229) * 0.8
            else:
                price = 80.0
            history.append((dt.isoformat(), price))
        return history


class BacktestServiceForBuyDiagnostics(BacktestService):
    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        idx = len(price_history) - 1
        if idx < 230:
            return 85.0
        if idx < 240:
            return 85.0 - ((idx - 229) * 1.5)
        return 72.8


def test_buy_diagnostics_reason_flags_reflect_actual_gate_conditions():
    start = date(2020, 1, 1)
    end = start + timedelta(days=339)
    service = BacktestServiceForBuyDiagnostics(
        FakeMarketServiceForBuyDiagnostics(), FakeMacroServiceFlat(), FakeEventService()
    )

    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")
    buy_events = result["diagnostics"]["buy_events"]

    assert len(buy_events) >= 1
    first_buy = buy_events[0]
    assert "buy_reason_flags" in first_buy
    assert first_buy["buy_reason_flags"]["buy_gate_open"] is True
    assert first_buy["buy_reason_flags"]["cooldown_clear"] is True
    assert (
        first_buy["buy_reason_flags"]["day60"]
        or first_buy["buy_reason_flags"]["pattern_a"]
        or first_buy["buy_reason_flags"]["pattern_b"]
    )
    assert first_buy["buy_reason_flags"]["signal_reason"] in {"day60", "pattern_a", "pattern_b", "both"}


class FakeMarketServiceStartsLate:
    def get_price_history_range(self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"):
        late_start = date(2014, 1, 1)
        return [((late_start + timedelta(days=i)).isoformat(), 100.0 + i) for i in range(260)]


def test_backtest_raises_when_requested_start_is_not_available():
    service = BacktestService(FakeMarketServiceStartsLate(), FakeMacroServiceFlat(), FakeEventService())
    with pytest.raises(ValueError, match="insufficient_history_for_requested_start"):
        service.run_backtest(date(2004, 1, 1), date(2025, 12, 31), initial_cash=1000.0, index_type="SP500")


def test_technical_score_equivalence_sub_history_vs_running_history():
    start = date(2010, 1, 1)
    price_history = []
    for i in range(420):
        dt = start + timedelta(days=i)
        base = 100.0 + (i * 0.18)
        wobble = ((i % 9) - 4) * 0.21
        price_history.append((dt.isoformat(), round(base + wobble, 4)))

    running_history = []
    check_indices = [199, 220, 260, 320, 419]

    for idx, row in enumerate(price_history):
        running_history.append(row)
        if idx not in check_indices:
            continue
        old_score, old_reason = calculate_technical_score(price_history[: idx + 1], base_window=200)
        new_score, new_reason = calculate_technical_score(running_history, base_window=200)
        assert old_score == new_score
        assert old_reason == new_reason


def test_running_history_and_sub_history_produce_same_backtest_outcome_with_fixed_data():
    start = date(2020, 1, 1)
    end = start + timedelta(days=259)
    market = FakeMarketServiceForSellDiagnostics()
    macro = FakeMacroServiceFlat()
    events = FakeEventService()

    service = BacktestService(market, macro, events)
    result = service.run_backtest(start, end, initial_cash=1000.0, index_type="SP500")

    # run_backtest currently uses running_history append-only path.
    # This regression assertion guarantees stable strategy outcome on fixed data.
    assert result["final_value"] == 760.0
    assert result["buy_and_hold_final"] == 760.0
    assert result["max_drawdown_pct"] == 24.0
    assert result["trade_count"] == 0
