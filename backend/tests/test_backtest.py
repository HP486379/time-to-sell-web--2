from datetime import date, timedelta
import os
import sys
from datetime import date, timedelta

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

    assert result["trade_count"] == 2
    assert result["trades"][0]["action"] == "BUY"
    assert result["trades"][1]["action"] == "SELL"
    # 10株を100で買い200で売る想定 → 2000円前後の評価
    assert result["final_value"] >= 2000.0
    assert result["buy_and_hold_final"] >= 2000.0
