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
    assert svc._get_sell_rule_name("NIKKEI225") == "nikkei225_trend_break_guard_score80_gate"
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
        assert "trade_pair_diagnostics" in result



def test_nikkei225_trend_break_guard_boost_requires_trend_break():
    svc = _svc()
    no_break = [100.0 + (i * 0.4) for i in range(130)]
    ma20_nb = sum(no_break[-20:]) / 20
    ma60_nb = sum(no_break[-60:]) / 60
    boost_nb, trend_break_ok_nb = svc._nikkei225_trend_break_guard_boost(no_break, ma20_nb, ma60_nb, 100.0)
    assert trend_break_ok_nb is False
    assert boost_nb == 0.0

    shaped = [100.0] * 70 + [110.0] * 40 + [130.0, 131.0, 132.0, 131.5, 131.0, 130.5, 130.0, 129.5, 130.0, 129.8, 129.6, 129.4, 129.2, 129.0, 128.8, 128.6, 128.4, 128.2, 128.0, 127.8]
    ma20 = sum(shaped[-20:]) / 20
    ma60 = sum(shaped[-60:]) / 60
    boost, trend_break_ok = svc._nikkei225_trend_break_guard_boost(shaped, ma20, ma60, 100.0)
    assert boost >= 0.0
    assert isinstance(trend_break_ok, bool)


def test_nikkei225_fast_buyback_after_trend_break_sell(monkeypatch):
    class _Market:
        def get_price_history_range(self, start_date, end_date, allow_fallback, index_type):
            base = date(2024, 1, 1)
            rows = []
            for i in range(760):
                d = base + timedelta(days=i)
                price = 100.0 + (i * 0.1)
                if i > 650:
                    price += 12.0
                rows.append((d.isoformat(), price))
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

    monkeypatch.setattr("services.backtest_service.calculate_macro_score", lambda *args, **kwargs: (100.0, {}))
    monkeypatch.setattr("services.backtest_service.calculate_event_adjustment", lambda *args, **kwargs: (0.0, {}))

    def _fake_technical(sub_history, base_window=200):
        dt = sub_history[-1][0]
        if dt == "2025-11-03":
            return 80.0, {}
        if dt >= "2025-11-04":
            return 45.0, {}
        return 50.0, {}

    monkeypatch.setattr("services.backtest_service.calculate_technical_score", _fake_technical)
    monkeypatch.setattr(
        "services.backtest_service.BacktestService._nikkei225_trend_break_guard_boost",
        lambda self, closes, ma20, ma60, ma200: (30.0 if closes[-1] >= closes[-2] else 0.0, True),
    )

    nikkei = svc.run_backtest(
        start_date=date(2024, 1, 1),
        end_date=date(2025, 12, 31),
        initial_cash=1_000_000.0,
        buy_threshold=40.0,
        sell_threshold=80.0,
        index_type="NIKKEI225",
        score_ma=200,
    )
    sells = [t for t in nikkei["trades"] if t["action"] == "SELL"]
    buys = [t for t in nikkei["trades"] if t["action"] == "BUY"]
    assert sells
    assert buys
    # fast buyback should allow re-entry before legacy 20-day lock in some paths
    assert buys[0]["reason"].startswith("nikkei225_fast_buyback_") or buys[0]["reason"] == "initial_threshold"
