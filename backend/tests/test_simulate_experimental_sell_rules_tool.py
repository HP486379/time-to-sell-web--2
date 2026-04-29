from datetime import date

from tools.simulate_experimental_sell_rules import (
    _run_simulation_core,
    _summarize_rule_result,
    build_index_rule_review_from_json,
    build_portfolio_rule_comparison_from_json,
    parse_index_types,
    run_comparison,
)


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


def test_parse_index_types_defaults_and_custom():
    assert parse_index_types(None) == [
        "SP500",
        "SP500_JPY",
        "TOPIX",
        "NIKKEI225",
        "NIFTY50",
        "ALLCOUNTRY",
        "ALLCOUNTRY_JPY",
    ]
    assert parse_index_types("SP500, TOPIX") == ["SP500", "TOPIX"]


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


def test_run_comparison_returns_requested_technical_variants(monkeypatch):
    def _fake_core(*args, **kwargs):
        return {
            "final_value": 1000.0,
            "buy_and_hold_final": 1000.0,
            "max_drawdown_pct": 8.0,
            "trades": [],
            "price_history": [("2020-01-01", 100.0)],
        }

    monkeypatch.setattr("tools.simulate_experimental_sell_rules._run_simulation_core", _fake_core)
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
        "no_ath_penalty_current_gate",
        "ath_boost_8_current_gate",
        "no_ath_penalty_score80_gate",
        "ath_boost_8_score80_gate",
        "no_ath_penalty_relaxed_gate",
        "ath_boost_8_relaxed_gate",
    ]
    assert "score_max" in rows[0]
    assert "score_ge_80_count" in rows[0]
    assert "sell_gate_blockers" in rows[0]
    assert "blocked_good_sell_candidate_count" in rows[0]
    assert "bad_sell_count" in rows[0]

class _MarketService:
    def get_price_history_range(self, start, end, allow_fallback, index_type):
        history = []
        for i in range(320):
            dt = start.fromordinal(start.toordinal() + i)
            history.append((dt.isoformat(), 100.0))
        return history


class _MacroService:
    def get_macro_series_range(self, start, end):
        values = []
        days = (end - start).days
        for i in range(days + 1):
            dt = start.fromordinal(start.toordinal() + i)
            values.append((dt, 0.0))
        return {"r_10y": values, "cpi": values, "vix": values}


class _BacktestServiceForSimulation:
    allow_fallback = False
    market_service = _MarketService()
    macro_service = _MacroService()
    event_service = type("_EventService", (), {"get_events_for_date": lambda self, current_date: []})()

    def _prepare_price_history(self, raw_history, index_type):
        return raw_history

    def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
        idx = len(price_history) - 1
        if idx == 200:
            return 80.0
        if idx >= 260:
            return 30.0
        return 50.0

    def _history_and_current(self, series, current_date):
        if not series:
            return [0.0], 0.0
        vals = [float(v) for d, v in series if d <= current_date]
        if len(vals) == 1:
            vals.append(vals[0])
        return vals[:-1], vals[-1]


class _SimulationContext:
    backtest_service = _BacktestServiceForSimulation()


def test_initial_position_is_not_in_buy_dates_and_buy_appears_only_after_sell(monkeypatch):
    def _fake_technical(price_history, base_window=200):
        idx = len(price_history) - 1
        return (80.0, {}) if idx == 200 else (40.0, {})

    monkeypatch.setattr("tools.simulate_experimental_sell_rules.calculate_technical_score", _fake_technical)
    result = _run_simulation_core(
        _SimulationContext(),
        index_type="SP500_JPY",
        rule_name="experimental",
        sell_threshold=70.0,
        technical_threshold=78.0,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 11, 15),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        score_ma=200,
    )
    sell_dates = [t["date"] for t in result["trades"] if t["action"] == "SELL"]
    buy_dates = [t["date"] for t in result["trades"] if t["action"] == "BUY"]
    assert len(sell_dates) == 1
    assert len(buy_dates) == 1
    assert buy_dates[0] > sell_dates[0]


def test_no_sell_case_keeps_final_equal_to_hold(monkeypatch):
    def _low_scores(price_history, base_window=200):
        return (40.0, {})

    monkeypatch.setattr("tools.simulate_experimental_sell_rules.calculate_technical_score", _low_scores)

    class _NoSellBacktestService(_BacktestServiceForSimulation):
        def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
            return 30.0

    class _NoSellContext:
        backtest_service = _NoSellBacktestService()

    result = _run_simulation_core(
        _NoSellContext(),
        index_type="SP500_JPY",
        rule_name="experimental",
        sell_threshold=70.0,
        technical_threshold=78.0,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 10, 30),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        score_ma=200,
    )
    assert result["trades"] == []
    assert result["final_value"] == result["buy_and_hold_final"]
    assert result["score_max"] <= 80.0
    assert "score_ge_80_count" in result
    assert "score_ge_80_sell_gate_details" in result
    assert "sell_loss_reasons" in result


def test_no_buy_is_recorded_before_first_sell_even_if_initial_cash_cannot_buy_one_share(monkeypatch):
    def _always_low_technical(price_history, base_window=200):
        return (40.0, {})

    monkeypatch.setattr("tools.simulate_experimental_sell_rules.calculate_technical_score", _always_low_technical)

    class _NoSellBacktestService(_BacktestServiceForSimulation):
        def _calculate_scores(self, price_history, macro_series, current_date, score_ma):
            return 30.0

    class _NoSellContext:
        backtest_service = _NoSellBacktestService()

    result = _run_simulation_core(
        _NoSellContext(),
        index_type="SP500_JPY",
        rule_name="experimental",
        sell_threshold=70.0,
        technical_threshold=78.0,
        start_date=date(2020, 1, 1),
        end_date=date(2020, 10, 30),
        initial_cash=50.0,
        buy_threshold=40.0,
        score_ma=200,
    )

    assert result["trades"] == []


def test_build_portfolio_rule_comparison_from_json(tmp_path):
    rows = []
    index_types = ["SP500", "SP500_JPY", "TOPIX", "NIKKEI225", "NIFTY50", "ALLCOUNTRY", "ALLCOUNTRY_JPY"]
    for index_type in index_types:
        for rule_name in ["current_logic", "no_ath_penalty_current_gate", "ath_boost_8_score80_gate", "no_ath_penalty_score80_gate"]:
            rows.append(
                {
                    "index_type": index_type,
                    "rule_name": rule_name,
                    "final_equity": 100.0,
                    "hold_equity": 100.0,
                    "diff_pct": 1.0 if rule_name != "current_logic" else 0.0,
                    "trade_count": 1,
                    "sell_count": 1,
                    "buy_count": 0,
                    "sell_dates": [],
                    "buy_dates": [],
                    "sell_post_return_20d_pct": [],
                    "buyback_return_pct": [],
                    "bad_sell_count": 0,
                    "blocked_good_sell_candidate_count": 0,
                    "max_drawdown": 1.0,
                }
            )
    p = tmp_path / "in.json"
    p.write_text(__import__("json").dumps(rows), encoding="utf-8")
    out = build_portfolio_rule_comparison_from_json(str(p))
    assert set(out.keys()) == {"summary", "details"}
    summaries = {s["portfolio_rule_name"]: s for s in out["summary"]}
    assert summaries["current_all"]["missing_count"] == 0
    assert summaries["jpy_conservative"]["missing_count"] == 0
    assert summaries["jpy_aggressive"]["missing_count"] == 0
    assert summaries["sp500_jpy_only"]["missing_count"] == 0
    assert summaries["allcountry_jpy_only"]["missing_count"] == 0
    assert summaries["safe_sp500jpy_only"]["missing_count"] == 0
    assert summaries["aggressive_jpy_dual"]["missing_count"] == 0

    def _pick(portfolio_rule_name, index_type):
        return [x for x in out["details"] if x["portfolio_rule_name"] == portfolio_rule_name and x["index_type"] == index_type][0]

    # current_all
    assert _pick("current_all", "SP500")["applied_rule_name"] == "current_logic"
    # jpy_conservative
    assert _pick("jpy_conservative", "SP500_JPY")["applied_rule_name"] == "no_ath_penalty_current_gate"
    assert _pick("jpy_conservative", "ALLCOUNTRY_JPY")["applied_rule_name"] == "no_ath_penalty_current_gate"
    assert _pick("jpy_conservative", "SP500")["applied_rule_name"] == "current_logic"
    # jpy_aggressive
    assert _pick("jpy_aggressive", "SP500_JPY")["applied_rule_name"] == "ath_boost_8_score80_gate"
    assert _pick("jpy_aggressive", "ALLCOUNTRY_JPY")["applied_rule_name"] == "no_ath_penalty_score80_gate"
    assert _pick("jpy_aggressive", "TOPIX")["applied_rule_name"] == "current_logic"
    # sp500_jpy_only
    assert _pick("sp500_jpy_only", "SP500_JPY")["applied_rule_name"] == "ath_boost_8_score80_gate"
    assert _pick("sp500_jpy_only", "ALLCOUNTRY_JPY")["applied_rule_name"] == "current_logic"
    # allcountry_jpy_only
    assert _pick("allcountry_jpy_only", "ALLCOUNTRY_JPY")["applied_rule_name"] == "no_ath_penalty_score80_gate"
    assert _pick("allcountry_jpy_only", "SP500_JPY")["applied_rule_name"] == "current_logic"
    # aliases
    assert _pick("safe_sp500jpy_only", "SP500_JPY")["applied_rule_name"] == "ath_boost_8_score80_gate"
    assert _pick("safe_sp500jpy_only", "ALLCOUNTRY_JPY")["applied_rule_name"] == "current_logic"
    assert _pick("aggressive_jpy_dual", "SP500_JPY")["applied_rule_name"] == "ath_boost_8_score80_gate"
    assert _pick("aggressive_jpy_dual", "ALLCOUNTRY_JPY")["applied_rule_name"] == "no_ath_penalty_score80_gate"


def test_build_portfolio_rule_comparison_reports_missing_items(tmp_path):
    rows = []
    for index_type in ["SP500", "SP500_JPY", "ALLCOUNTRY_JPY"]:
        for rule_name in ["current_logic", "no_ath_penalty_current_gate"]:
            rows.append(
                {
                    "index_type": index_type,
                    "rule_name": rule_name,
                    "final_equity": 100.0,
                    "hold_equity": 100.0,
                    "diff_pct": 0.0,
                    "trade_count": 0,
                    "sell_count": 0,
                    "buy_count": 0,
                }
            )
    p = tmp_path / "in_missing.json"
    p.write_text(__import__("json").dumps(rows), encoding="utf-8")
    out = build_portfolio_rule_comparison_from_json(str(p))
    summaries = {s["portfolio_rule_name"]: s for s in out["summary"]}
    assert summaries["current_all"]["missing_count"] == 0
    assert summaries["jpy_aggressive"]["missing_count"] > 0
    assert len(summaries["jpy_aggressive"]["missing_items"]) > 0


def test_build_index_rule_review_from_json(tmp_path):
    rows = [
        {"index_type": "SP500_JPY", "rule_name": "current_logic", "diff_pct": 1.0, "bad_sell_count": 0, "trade_count": 1},
        {"index_type": "SP500_JPY", "rule_name": "ath_boost_8_score80_gate", "diff_pct": 5.0, "bad_sell_count": 0, "trade_count": 2, "sell_post_return_20d_pct": [-5.0]},
        {"index_type": "ALLCOUNTRY_JPY", "rule_name": "current_logic", "diff_pct": 0.5, "bad_sell_count": 0, "trade_count": 1},
        {"index_type": "ALLCOUNTRY_JPY", "rule_name": "no_ath_penalty_score80_gate", "diff_pct": 6.0, "bad_sell_count": 1, "trade_count": 2, "sell_post_return_20d_pct": [-2.0]},
        {"index_type": "TOPIX", "rule_name": "current_logic", "diff_pct": 0.0, "bad_sell_count": 0, "trade_count": 0},
        {"index_type": "TOPIX", "rule_name": "ath_boost_8_score80_gate", "diff_pct": 0.5, "bad_sell_count": 0, "trade_count": 3, "sell_post_return_20d_pct": [1.0]},
        {"index_type": "NIKKEI225", "rule_name": "ath_boost_8_score80_gate", "diff_pct": 3.0, "bad_sell_count": 0, "trade_count": 1},
    ]
    p = tmp_path / "review.json"
    p.write_text(__import__("json").dumps(rows), encoding="utf-8")
    out = build_index_rule_review_from_json(str(p))
    assert set(out.keys()) == {"summary", "details"}
    s = {x["index_type"]: x for x in out["summary"]}
    assert s["SP500_JPY"]["recommended_rule_name"] == "ath_boost_8_score80_gate"
    assert s["SP500_JPY"]["recommendation"] == "adopt"
    assert s["ALLCOUNTRY_JPY"]["recommended_rule_name"] == "no_ath_penalty_score80_gate"
    assert s["ALLCOUNTRY_JPY"]["recommendation"] == "needs_review"
    assert s["TOPIX"]["recommendation"] in {"keep_current", "needs_review"}
    assert s["NIKKEI225"]["missing_items"] != []
