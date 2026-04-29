from datetime import date

from tools.compare_sell_thresholds import parse_index_types, parse_thresholds, run_comparison


def _fake_run_backtest(
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
        "max_drawdown_pct": 12.3,
        "diagnostics": {
            "trade_summary": {"sell_count": 1, "buy_count": 1},
            "score_max": 88.8,
            "sell_threshold_hit_days": 5,
            "sell_gate_open_days": 2,
            "score_threshold_true_but_gate_closed_days": 4,
            "sell_gate_open_but_score_below_threshold_days": 1,
            "sell_signal_count": 1,
            "sell_events": [
                {
                    "date": "2025-01-10",
                    "sell_reason": ["sell_gate_open", "score_threshold"],
                    "post_return_20d_pct": 1.2,
                    "return_until_buyback_pct": 0.8,
                }
            ],
            "buy_events": [{"date": "2025-01-20", "buy_reason": ["buy_gate_open", "day60"]}],
        },
    }


def test_parse_index_types_returns_only_requested_indexes():
    values = parse_index_types("SP500,NIKKEI225")
    assert values == ["SP500", "NIKKEI225"]


def test_parse_thresholds_returns_only_requested_thresholds():
    values = parse_thresholds("70,75,85")
    assert values == [70.0, 75.0, 85.0]


def test_run_comparison_executes_only_specified_indexes_and_thresholds():
    calls = []

    def _recording_run_backtest(*args):
        calls.append((args[5], args[4]))
        return _fake_run_backtest(*args)

    rows = run_comparison(
        _recording_run_backtest,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        thresholds=[70.0, 85.0],
        index_types=["SP500"],
        score_ma=200,
    )

    assert calls == [("SP500", 70.0), ("SP500", 85.0)]
    assert len(rows) == 2


def test_run_comparison_contains_required_summary_fields():
    rows = run_comparison(
        _fake_run_backtest,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        thresholds=[80.0],
        index_types=["NIKKEI225"],
        score_ma=200,
    )

    row = rows[0]
    assert row["final_equity"] == 1100.0
    assert row["hold_equity"] == 1000.0
    assert row["diff_amount"] == 100.0
    assert row["trade_count"] == 2
    assert row["sell_count"] == 1
    assert row["buy_count"] == 1
    assert row["max_score"] == 88.8
    assert row["sell_threshold_hit_days"] == 5
    assert row["sell_gate_open_days"] == 2
    assert row["score_threshold_true_but_gate_closed_days"] == 4
    assert row["sell_gate_open_but_score_below_threshold_days"] == 1
    assert row["sell_signal_count"] == 1


def test_run_comparison_fallback_calculates_score_threshold_true_but_gate_closed_days():
    def _fake_without_explicit_breakdown(*args):
        return {
            "final_value": 1100.0,
            "buy_and_hold_final": 1000.0,
            "trade_count": 0,
            "max_drawdown_pct": 12.3,
            "diagnostics": {
                "trade_summary": {"sell_count": 0, "buy_count": 0},
                "sell_threshold_hit_days": 3,
                "sell_signal_count": 1,
                "sell_events": [],
                "buy_events": [],
            },
        }

    rows = run_comparison(
        _fake_without_explicit_breakdown,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        thresholds=[80.0],
        index_types=["SP500"],
        score_ma=200,
    )

    row = rows[0]
    assert row["score_threshold_true_but_gate_closed_days"] == 2
