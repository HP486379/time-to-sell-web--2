from datetime import date
from datetime import timedelta

from services.backtest_service import BacktestService


class _DummyService:
    def get_price_history_range(self, *args, **kwargs):
        return []


class _DummyEventService:
    def get_events_for_date(self, d):
        return []


def _svc():
    return BacktestService(_DummyService(), _DummyService(), _DummyEventService())


def test_index_sell_rule_map_selection():
    svc = _svc()
    assert svc._get_sell_rule_name("SP500_JPY") == "ath_boost_8_score80_gate"
    assert svc._get_sell_rule_name("ALLCOUNTRY_JPY") == "no_ath_penalty_score80_gate"
    assert svc._get_sell_rule_name("TOPIX") == "topix_overheat_guard_score80_gate"
    assert svc._get_sell_rule_name("NIKKEI225") == "nikkei225_spike_reversal_guard_score80_gate"
    for index_type in ["SP500", "NIFTY50", "ALLCOUNTRY"]:
        assert svc._get_sell_rule_name(index_type) == "current_logic"


def test_technical_variant_boost_behaves_as_expected():
    svc = _svc()
    closes = [100.0] * 59 + [120.0]
    base = 60.0
    assert svc._apply_technical_sell_variant("ath_boost_8_score80_gate", base, closes) == 68.0
    assert svc._apply_technical_sell_variant("no_ath_penalty_score80_gate", base, closes) == 72.0
    assert svc._apply_technical_sell_variant("current_logic", base, closes) == 60.0


def test_jpy_indices_use_score80_gate_sell_and_existing_buy_flow(monkeypatch):
    class _Market:
        def get_price_history_range(self, start_date, end_date, allow_fallback, index_type):
            base = date(2024, 1, 1)
            rows = []
            for i in range(760):
                d = base + timedelta(days=i)
                rows.append((d.isoformat(), 100.0))
            return rows

    class _Macro:
        def get_macro_series_range(self, start, end):
            vals = []
            days = (end - start).days
            for i in range(days + 1):
                d = start + timedelta(days=i)
                vals.append((d, 0.0))
            return {"r_10y": vals, "cpi": vals, "vix": vals}

    class _Event:
        def get_events_for_date(self, d):
            return []

    svc = BacktestService(_Market(), _Macro(), _Event())

    sell_buy_map = {
        "SP500_JPY": {
            "sell": {"2025-11-03"},
            "buy": {"2026-01-02"},
        },
        "ALLCOUNTRY_JPY": {
            "sell": {"2025-11-03"},
            "buy": {"2026-01-02"},
        },
    }

    def _fake_technical(sub_history, base_window=200):
        dt = sub_history[-1][0]
        if dt in {"2024-07-05", "2025-11-03"}:
            return 80.0, {}
        if dt in {"2024-08-09", "2025-12-02"}:
            return 0.0, {}
        return 50.0, {}

    monkeypatch.setattr("services.backtest_service.calculate_technical_score", _fake_technical)
    monkeypatch.setattr("services.backtest_service.calculate_macro_score", lambda *args, **kwargs: (100.0, {}))
    monkeypatch.setattr("services.backtest_service.calculate_event_adjustment", lambda *args, **kwargs: (0.0, {}))

    for index_type, expected in sell_buy_map.items():
        result = svc.run_backtest(
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            initial_cash=1_000_000.0,
            buy_threshold=40.0,
            sell_threshold=80.0,
            index_type=index_type,
            score_ma=200,
        )
        sell_dates = {t["date"] for t in result["trades"] if t["action"] == "SELL"}
        buy_dates = {t["date"] for t in result["trades"] if t["action"] == "BUY"}
        assert expected["sell"].issubset(sell_dates)
        assert expected["buy"].issubset(buy_dates)


def test_nikkei225_spike_reversal_guard_boost_only_for_matching_shape():
    svc = _svc()
    closes = [100.0] * 70 + [105.0] * 40 + [110.0 + i for i in range(19)] + [127.0]
    ma20 = sum(closes[-20:]) / 20
    ma60 = sum(closes[-60:]) / 60
    ma200 = 100.0
    boost = svc._nikkei225_spike_reversal_guard_boost(closes, ma20, ma60, ma200)
    assert boost in {20.0, 30.0}

    non_matching = [100.0] * 130
    ma20_flat = sum(non_matching[-20:]) / 20
    ma60_flat = sum(non_matching[-60:]) / 60
    assert svc._nikkei225_spike_reversal_guard_boost(non_matching, ma20_flat, ma60_flat, 100.0) == 0.0
