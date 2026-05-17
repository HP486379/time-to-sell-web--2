from __future__ import annotations

import importlib.abc
import importlib.machinery
import math
import os
import sys
from datetime import date
from math import floor
from typing import Any

_RUNTIME_MAX_DAYS = int(os.getenv("BACKTEST_RUNTIME_MAX_DAYS", str(366 * 3)))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _long_runtime_guard_disabled() -> bool:
    # Precomputed generation intentionally runs long ranges locally.
    if _truthy(os.getenv("BACKTEST_ALLOW_LONG_RUNTIME")):
        return True
    if os.getenv("PRECOMPUTED_PRESETS") or os.getenv("PRECOMPUTED_TARGETS"):
        return True
    return any(str(arg).endswith("generate_precomputed_backtests.py") for arg in sys.argv)


def _raise_long_runtime_rejected(start_date: date, end_date: date, index_type: str) -> None:
    try:
        from fastapi import HTTPException
    except Exception as exc:  # pragma: no cover - FastAPI is present in API runtime.
        raise ValueError(
            "runtime_backtest_range_too_long:"
            f"index_type={index_type},requested_start={start_date.isoformat()},"
            f"end_date={end_date.isoformat()},max_runtime_days={_RUNTIME_MAX_DAYS}"
        ) from exc

    raise HTTPException(
        status_code=400,
        detail={
            "error": "runtime_backtest_range_too_long",
            "index_type": index_type,
            "requested_start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "max_runtime_days": _RUNTIME_MAX_DAYS,
            "message": "3年超のバックテストは事前計算済み期間のみ利用できます。",
        },
    )


def _compute_max_drawdown(values: list[float]) -> float:
    if not values:
        return 0.0
    peak = values[0]
    max_dd = 0.0
    for value in values:
        if value > peak:
            peak = value
        if peak > 0:
            max_dd = max(max_dd, (peak - value) / peak)
    return round(max_dd * 100.0, 2)


def _parse_accumulation_payload(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        start_date = date.fromisoformat(str(payload.get("start_date")))
        end_date = date.fromisoformat(str(payload.get("end_date")))
    except Exception as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail={"error": "invalid_date"}) from exc

    if end_date < start_date:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail={"error": "end_date_before_start_date"})

    index_type = str(payload.get("index_type") or "SP500").upper()
    if index_type in {"SP500_JPY", "TOPIX", "NIKKEI225", "NIFTY50", "ALLCOUNTRY", "ALLCOUNTRY_JPY", "SP500"}:
        pass
    elif index_type in {"NIKKEI", "NIKKEI225_JPY"}:
        index_type = "NIKKEI225"
    elif index_type in {"ORUKAN", "ORUKAN_JPY"}:
        index_type = "ALLCOUNTRY_JPY"
    else:
        index_type = "SP500"

    def finite_float(name: str, default: float) -> float:
        value = payload.get(name, default)
        try:
            parsed = float(value)
        except (TypeError, ValueError) as exc:
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail={"error": f"invalid_{name}"}) from exc
        if not math.isfinite(parsed):
            from fastapi import HTTPException

            raise HTTPException(status_code=400, detail={"error": f"invalid_{name}"})
        return parsed

    score_ma = int(finite_float("score_ma", 200.0))
    return {
        "start_date": start_date,
        "end_date": end_date,
        "index_type": index_type,
        "initial_cash": finite_float("initial_cash", 0.0),
        "monthly_amount": finite_float("monthly_amount", 30000.0),
        "profit_take_pct": finite_float("profit_take_pct", 20.0),
        "sell_threshold": finite_float("sell_threshold", 80.0),
        "buy_threshold": finite_float("buy_threshold", 40.0),
        "score_ma": score_ma,
    }


def _run_accumulation_backtest_endpoint(payload: dict[str, Any]) -> dict[str, Any]:
    from fastapi import HTTPException
    from scoring.technical import moving_average

    params = _parse_accumulation_payload(payload)
    start_date = params["start_date"]
    end_date = params["end_date"]
    index_type = params["index_type"]

    if (end_date - start_date).days > _RUNTIME_MAX_DAYS and not _long_runtime_guard_disabled():
        _raise_long_runtime_rejected(start_date, end_date, index_type)

    if params["monthly_amount"] < 0 or params["initial_cash"] < 0:
        raise HTTPException(status_code=400, detail={"error": "cash_amount_must_be_non_negative"})
    if params["profit_take_pct"] < 0 or params["profit_take_pct"] > 100:
        raise HTTPException(status_code=400, detail={"error": "profit_take_pct_out_of_range"})
    if params["score_ma"] < 2:
        raise HTTPException(status_code=400, detail={"error": "invalid_score_ma"})

    main_module = sys.modules.get("main") or sys.modules.get("__main__")
    service = getattr(main_module, "backtest_service", None) if main_module is not None else None
    if service is None:
        raise HTTPException(status_code=503, detail={"error": "backtest_service_unavailable"})

    price_history = service.fetch_and_validate_price_history_for_backtest(start_date, end_date, index_type)
    required_points = max(200, int(params["score_ma"]))
    if len(price_history) < required_points:
        raise HTTPException(status_code=400, detail={"error": "not_enough_price_history", "required_points": required_points})

    macro_series = service.macro_service.get_macro_series_range(start_date, end_date)
    events_cache: dict[str, list[dict[str, Any]]] = {}
    running_history: list[tuple[str, float]] = []
    closes: list[float] = []

    strategy_cash = float(params["initial_cash"])
    hold_cash = float(params["initial_cash"])
    strategy_shares = 0
    hold_shares = 0
    total_contributed = float(params["initial_cash"])
    contribution_count = 0
    trade_count = 0
    deferred_contribution_count = 0
    deferred_contribution_amount = 0.0
    reinvest_count = 0
    last_contribution_month: tuple[int, int] | None = None

    portfolio_history: list[dict[str, Any]] = []
    buy_hold_history: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    daily_scores: list[dict[str, Any]] = []
    sell_candidate_dates: list[dict[str, Any]] = []
    near_sell_candidate_dates: list[dict[str, Any]] = []
    buy_candidate_dates: list[dict[str, Any]] = []

    for idx, (date_str, close_raw) in enumerate(price_history):
        close = float(close_raw)
        current_dt = date.fromisoformat(date_str)
        running_history.append((date_str, close))
        closes.append(close)
        month_key = (current_dt.year, current_dt.month)
        is_contribution_day = last_contribution_month != month_key

        score = None
        if idx >= max(int(params["score_ma"]) - 1, 199):
            try:
                score = float(service._calculate_scores(
                    running_history,
                    macro_series,
                    current_dt,
                    int(params["score_ma"]),
                    events_cache=events_cache,
                ))
            except TypeError:
                score = float(service._calculate_scores(running_history, macro_series, current_dt, int(params["score_ma"])))
            score_row = {"date": date_str, "score": round(score, 4), "close": round(close, 4)}
            daily_scores.append(score_row)

            if score >= float(params["sell_threshold"]):
                sell_candidate_dates.append(score_row)
            elif score >= max(float(params["sell_threshold"]) - 5.0, 0.0):
                near_sell_candidate_dates.append(score_row)

            if score < float(params["buy_threshold"]):
                buy_candidate_dates.append(score_row)

        if is_contribution_day:
            last_contribution_month = month_key
            monthly_amount = float(params["monthly_amount"])
            if monthly_amount > 0:
                hold_cash += monthly_amount
                strategy_cash += monthly_amount
                total_contributed += monthly_amount
                contribution_count += 1
                if score is not None and score >= float(params["sell_threshold"]):
                    deferred_contribution_count += 1
                    deferred_contribution_amount += monthly_amount
                    trades.append({
                        "action": "DEFER_CONTRIBUTION",
                        "date": date_str,
                        "amount": monthly_amount,
                        "price": close,
                        "score": round(score, 4),
                        "reason": "overheat_defer_monthly_contribution",
                    })
                else:
                    if strategy_cash >= close:
                        qty = floor(strategy_cash / close)
                        if qty > 0:
                            strategy_cash -= qty * close
                            strategy_shares += qty

        if hold_cash >= close:
            hold_qty = floor(hold_cash / close)
            if hold_qty > 0:
                hold_cash -= hold_qty * close
                hold_shares += hold_qty

        if score is not None and strategy_cash >= close and score < float(params["buy_threshold"]):
            buy_qty = floor(strategy_cash / close)
            if buy_qty > 0:
                strategy_cash -= buy_qty * close
                strategy_shares += buy_qty
                trade_count += 1
                reinvest_count += 1
                trades.append({
                    "action": "BUY_REINVEST",
                    "date": date_str,
                    "quantity": buy_qty,
                    "price": close,
                    "score": round(score, 4),
                    "reason": "cooldown_reinvest_deferred_cash",
                })

        strategy_value = strategy_cash + strategy_shares * close
        hold_value = hold_cash + hold_shares * close
        portfolio_history.append({"date": date_str, "value": round(strategy_value, 2)})
        buy_hold_history.append({"date": date_str, "value": round(hold_value, 2)})

    final_value = portfolio_history[-1]["value"] if portfolio_history else 0.0
    buy_hold_final = buy_hold_history[-1]["value"] if buy_hold_history else 0.0
    total_return_pct = round(((final_value / total_contributed) - 1.0) * 100.0, 2) if total_contributed > 0 else 0.0
    hold_return_pct = round(((buy_hold_final / total_contributed) - 1.0) * 100.0, 2) if total_contributed > 0 else 0.0
    max_dd = _compute_max_drawdown([row["value"] for row in portfolio_history])

    ma20 = moving_average(closes, 20)
    ma60 = moving_average(closes, 60)
    ma200 = moving_average(closes, 200)
    price_points = []
    for idx, (date_str, close_raw) in enumerate(price_history):
        price_points.append({
            "date": date_str,
            "close": float(close_raw),
            "ma20": ma20[idx] if idx < len(ma20) else None,
            "ma60": ma60[idx] if idx < len(ma60) else None,
            "ma200": ma200[idx] if idx < len(ma200) else None,
        })

    top_score_dates = sorted(daily_scores, key=lambda row: row["score"], reverse=True)[:5]

    return {
        "summary": {
            "final_equity": final_value,
            "hold_equity": buy_hold_final,
            "total_return": total_return_pct,
            "hold_return": hold_return_pct,
            "max_drawdown": max_dd,
            "trade_count": trade_count,
            "final_asset": final_value,
            "buy_and_hold_asset": buy_hold_final,
            "total_contributed": round(total_contributed, 2),
            "monthly_amount": float(params["monthly_amount"]),
            "profit_take_pct": float(params["profit_take_pct"]),
            "profit_take_count": 0,
            "deferred_contribution_count": deferred_contribution_count,
            "deferred_contribution_amount": round(deferred_contribution_amount, 2),
            "reinvest_count": reinvest_count,
            "contribution_count": contribution_count,
            "waiting_cash": round(strategy_cash, 2),
        },
        "equity_curve": price_points,
        "portfolio_history": portfolio_history,
        "buy_hold_history": buy_hold_history,
        "trades": trades,
        "diagnostics": {
            "result_source": "runtime_accumulation",
            "backtest_type": "accumulation",
            "index_type": index_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "score_ma": params["score_ma"],
            "sell_threshold": params["sell_threshold"],
            "buy_threshold": params["buy_threshold"],
            "sell_policy": "defer_monthly_contribution_when_overheated",
            "index_specific_sell_adjustment_applied": False,
            "index_specific_sell_adjustment_note": "積立版では保有分を売却せず、過熱時は新規積立分だけを一時待機し、冷却時に再投入する。",
            "score_samples": {
                "first_score_date": daily_scores[0]["date"] if daily_scores else None,
                "first_score": daily_scores[0]["score"] if daily_scores else None,
                "min_score": min((row["score"] for row in daily_scores), default=None),
                "max_score": max((row["score"] for row in daily_scores), default=None),
                "days_score_above_sell_threshold": len(sell_candidate_dates),
                "days_score_above_near_sell_threshold": len(near_sell_candidate_dates),
                "near_sell_threshold": max(float(params["sell_threshold"]) - 5.0, 0.0),
                "days_score_below_buy_threshold": len(buy_candidate_dates),
            },
            "accumulation_diagnostics": {
                "sell_candidate_count": len(sell_candidate_dates),
                "near_sell_candidate_count": len(near_sell_candidate_dates),
                "buy_candidate_count": len(buy_candidate_dates),
                "deferred_contribution_count": deferred_contribution_count,
                "deferred_contribution_amount": round(deferred_contribution_amount, 2),
                "top_score_dates": top_score_dates,
                "sell_candidate_dates": sell_candidate_dates[:10],
                "near_sell_candidate_dates": near_sell_candidate_dates[:10],
                "buy_candidate_dates": buy_candidate_dates[:10],
                "blocked_sell_dates": [],
                "no_trade_reason": (
                    "score_never_reached_sell_threshold" if not sell_candidate_dates else
                    "no_monthly_contribution_on_sell_candidate_dates" if deferred_contribution_count == 0 else
                    None
                ),
            },
        },
    }


def _install_accumulation_backtest_route(app: Any) -> None:
    if getattr(app, "_accumulation_backtest_route_installed", False):
        return
    app.post("/api/backtest/accumulation")(_run_accumulation_backtest_endpoint)
    app._accumulation_backtest_route_installed = True


def _patch_fastapi_for_accumulation_route() -> None:
    try:
        from fastapi import FastAPI
    except Exception:
        return
    if getattr(FastAPI, "_accumulation_backtest_patch_installed", False):
        return
    original_init = FastAPI.__init__

    def patched_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        _install_accumulation_backtest_route(self)

    FastAPI.__init__ = patched_init
    FastAPI._accumulation_backtest_patch_installed = True


def _patch_backtest_service(module: Any) -> None:
    service_cls = getattr(module, "BacktestService", None)
    if service_cls is None or getattr(service_cls, "_long_runtime_guard_installed", False):
        return

    original = service_cls.fetch_and_validate_price_history_for_backtest

    def guarded_fetch_and_validate(self, start_date: date, end_date: date, index_type: str):
        if (
            not _long_runtime_guard_disabled()
            and start_date is not None
            and end_date is not None
            and (end_date - start_date).days > _RUNTIME_MAX_DAYS
        ):
            _raise_long_runtime_rejected(start_date, end_date, index_type)
        return original(self, start_date, end_date, index_type)

    service_cls.fetch_and_validate_price_history_for_backtest = guarded_fetch_and_validate
    service_cls._long_runtime_guard_installed = True


class _BacktestServicePatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader):
        self._wrapped = wrapped

    def create_module(self, spec):
        create_module = getattr(self._wrapped, "create_module", None)
        if create_module is None:
            return None
        return create_module(spec)

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        _patch_backtest_service(module)


class _BacktestServicePatchFinder(importlib.abc.MetaPathFinder):
    TARGET = "services.backtest_service"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is None or spec.loader is None:
                continue
            if not isinstance(spec.loader, _BacktestServicePatchLoader):
                spec.loader = _BacktestServicePatchLoader(spec.loader)
            return spec
        return None


_patch_fastapi_for_accumulation_route()

if "services.backtest_service" in sys.modules:
    _patch_backtest_service(sys.modules["services.backtest_service"])
elif not any(isinstance(finder, _BacktestServicePatchFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _BacktestServicePatchFinder())
