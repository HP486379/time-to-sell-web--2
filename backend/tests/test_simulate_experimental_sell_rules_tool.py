from datetime import date

from tools.simulate_experimental_sell_rules import _summarize_rule_result, run_comparison


class FakeBacktestService:
    def run_backtest(
        self,
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float,
        sell_threshold: float,
        index_type: str,
        score_ma: int,
    ):
        return {
            "final_value": 1200.0,
            "buy_and_hold_final": 1000.0,
            "max_drawdown_pct": 10.0,
            "trades": [
                {"action": "SELL", "date": "2020-01-01", "quantity": 10, "price": 100.0},
                {"action": "BUY", "date": "2020-01-10", "quantity": 10, "price": 95.0, "reason": "day60"},
            ],
            "price_history": [
                ("2020-01-01", 100.0),
                ("2020-01-02", 99.0),
                ("2020-01-03", 98.0),
                ("2020-01-04", 97.0),
                ("2020-01-05", 96.0),
                ("2020-01-06", 95.0),
                ("2020-01-07", 94.0),
                ("2020-01-08", 93.0),
                ("2020-01-09", 92.0),
                ("2020-01-10", 91.0),
                ("2020-01-11", 90.0),
                ("2020-01-12", 89.0),
                ("2020-01-13", 88.0),
                ("2020-01-14", 87.0),
                ("2020-01-15", 86.0),
                ("2020-01-16", 85.0),
                ("2020-01-17", 84.0),
                ("2020-01-18", 83.0),
                ("2020-01-19", 82.0),
                ("2020-01-20", 81.0),
                ("2020-01-21", 80.0),
            ],
        }


class FakeContext:
    backtest_service = FakeBacktestService()


def test_summarize_rule_result_contains_required_fields():
    result = FakeBacktestService().run_backtest(
        date(2020, 1, 1), date(2020, 12, 31), 1_000_000.0, 40.0, 80.0, "SP500_JPY", 200
    )
    row = _summarize_rule_result("current_logic", "SP500_JPY", result)

    assert row["rule_name"] == "current_logic"
    assert row["index_type"] == "SP500_JPY"
    assert row["final_equity"] == 1200.0
    assert row["hold_equity"] == 1000.0
    assert row["diff_amount"] == 200.0
    assert row["trade_count"] == 2
    assert row["sell_count"] == 1
    assert row["buy_count"] == 1


def test_run_comparison_runs_three_rule_variants(monkeypatch):
    def _fake_experimental(*args, **kwargs):
        return {
            "final_value": 1100.0,
            "buy_and_hold_final": 1000.0,
            "max_drawdown_pct": 8.0,
            "trades": [],
            "price_history": [("2020-01-01", 100.0)],
        }

    monkeypatch.setattr("tools.simulate_experimental_sell_rules.run_experimental_rule", _fake_experimental)
    rows = run_comparison(
        ctx=FakeContext(),
        index_type="SP500_JPY",
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        score_ma=200,
    )
    assert [row["rule_name"] for row in rows] == [
        "current_logic",
        "experimental_total70_technical75",
        "experimental_total70_technical78",
    ]
