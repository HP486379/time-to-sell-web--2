from datetime import date

from tools.analyze_sell_candidates import (
    _forward_max_drawdown,
    _forward_return,
    _passes_filters,
    parse_index_types,
    run_analysis,
)


def test_parse_index_types_only_uses_requested_indexes():
    assert parse_index_types("TOPIX,SP500_JPY") == ["TOPIX", "SP500_JPY"]


def test_forward_metrics_are_calculated():
    history = [
        ("2020-01-01", 100.0),
        ("2020-01-02", 90.0),
        ("2020-01-03", 95.0),
        ("2020-01-04", 110.0),
    ]
    assert _forward_return(history, 0, 2) == -5.0
    assert _forward_max_drawdown(history, 0, 2) == -10.0


def test_run_analysis_uses_only_specified_index_and_threshold(monkeypatch):
    calls = []

    def _fake_analyze_single_index(
        ctx,
        *,
        index_type: str,
        min_total_score: float,
        min_technical_score: float | None,
        min_macro_score: float | None,
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float,
        score_ma: int,
    ):
        calls.append((index_type, min_total_score, min_technical_score, min_macro_score))
        return {
            "index_type": index_type,
            "threshold": min_total_score,
            "candidates": [
                {
                    "index_type": index_type,
                    "candidate_threshold": min_total_score,
                    "date": "2020-01-01",
                    "close": 100.0,
                    "total_score": 70.0,
                    "technical_score": 30.0,
                    "macro_score": 30.0,
                    "event_adjustment": 10.0,
                    "was_actual_sell": False,
                    "sell_gate_open": False,
                    "sell_reason_flags": None,
                    "post_return_20d_pct": 1.0,
                    "post_return_60d_pct": 2.0,
                    "max_drawdown_next_20d_pct": -1.0,
                    "max_drawdown_next_60d_pct": -2.0,
                }
            ],
            "summary": {"candidate_count": 1},
        }

    monkeypatch.setattr("tools.analyze_sell_candidates.analyze_single_index", _fake_analyze_single_index)
    payload = run_analysis(
        ctx=None,
        index_types=["TOPIX"],
        min_total_score=70.0,
        min_technical_score=75.0,
        min_macro_score=None,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        score_ma=200,
    )

    assert calls == [("TOPIX", 70.0, 75.0, None)]
    row = payload["results"][0]["candidates"][0]
    assert row["total_score"] >= 70.0
    assert row["post_return_20d_pct"] == 1.0
    assert row["post_return_60d_pct"] == 2.0


def test_passes_filters_supports_total_technical_macro_combinations():
    assert _passes_filters(
        total_score=70.0,
        technical_score=74.0,
        macro_score=10.0,
        min_total_score=70.0,
        min_technical_score=None,
        min_macro_score=None,
    )
    assert not _passes_filters(
        total_score=70.0,
        technical_score=74.9,
        macro_score=10.0,
        min_total_score=70.0,
        min_technical_score=75.0,
        min_macro_score=None,
    )
    assert _passes_filters(
        total_score=72.0,
        technical_score=75.0,
        macro_score=12.0,
        min_total_score=72.0,
        min_technical_score=75.0,
        min_macro_score=10.0,
    )
