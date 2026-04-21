from __future__ import annotations

from datetime import date
from math import floor
from typing import Dict, List, Tuple

import logging
import math
import os
from scoring.events import calculate_event_adjustment
from scoring.macro import calculate_macro_score
from scoring.technical import (
    calculate_technical_score,
    calculate_ultra_long_mas,
    calculate_ultra_long_trend_context,
)
from scoring.total_score import calculate_total_score

logger = logging.getLogger(__name__)


class BacktestService:
    def __init__(self, market_service, macro_service, event_service):
        self.market_service = market_service
        self.macro_service = macro_service
        self.event_service = event_service
        # 実データを優先し、明示的に許可されたときのみシンセティックを利用する
        self.allow_fallback = os.getenv("BACKTEST_ALLOW_FALLBACK", "0").lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        logging.getLogger(__name__).info(
            "[BACKTEST CONFIG] BACKTEST_ALLOW_FALLBACK=%s", self.allow_fallback
        )

    def _safe_float(self, value, *, field_name: str) -> float:
        if isinstance(value, bool):
            raise ValueError(f"invalid_{field_name}:boolean_not_allowed")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"invalid_{field_name}:not_numeric({value!r})") from exc
        if not math.isfinite(number):
            raise ValueError(f"invalid_{field_name}:non_finite({value!r})")
        return number

    def _prepare_price_history(
        self, raw_history: List[Tuple[str, float]], index_type: str
    ) -> List[Tuple[str, float]]:
        sanitized: List[Tuple[str, float]] = []
        nan_like_count = 0
        invalid_count = 0
        invalid_samples: List[str] = []
        first_raw_date = raw_history[0][0] if raw_history else None
        last_raw_date = raw_history[-1][0] if raw_history else None

        for idx, row in enumerate(raw_history):
            if not isinstance(row, tuple) or len(row) != 2:
                invalid_count += 1
                if len(invalid_samples) < 5:
                    invalid_samples.append(f"idx={idx}:malformed_row:{row!r}")
                continue
            date_str, close_raw = row
            try:
                parsed_date = date.fromisoformat(str(date_str))
            except Exception:
                invalid_count += 1
                if len(invalid_samples) < 5:
                    invalid_samples.append(f"idx={idx}:invalid_date:{date_str!r}")
                continue
            try:
                close = self._safe_float(close_raw, field_name="close")
            except ValueError as exc:
                invalid_count += 1
                if "non_finite" in str(exc):
                    nan_like_count += 1
                if len(invalid_samples) < 5:
                    invalid_samples.append(f"idx={idx}:{exc}")
                continue
            if close <= 0:
                invalid_count += 1
                if len(invalid_samples) < 5:
                    invalid_samples.append(f"idx={idx}:invalid_close_non_positive:{close}")
                continue
            sanitized.append((parsed_date.isoformat(), close))

        first_date = sanitized[0][0] if sanitized else None
        last_date = sanitized[-1][0] if sanitized else None
        first_price = sanitized[0][1] if sanitized else None
        last_price = sanitized[-1][1] if sanitized else None
        logger.info(
            "[backtest] index_type=%s rows=%d sanitized_rows=%d first_raw_date=%s last_raw_date=%s first_date=%s last_date=%s "
            "first_price=%s last_price=%s invalid_rows=%d nan_like_rows=%d",
            index_type,
            len(raw_history),
            len(sanitized),
            first_raw_date,
            last_raw_date,
            first_date,
            last_date,
            first_price,
            last_price,
            invalid_count,
            nan_like_count,
        )
        if invalid_samples:
            logger.warning(
                "[backtest] index_type=%s invalid_price_rows_sample=%s",
                index_type,
                invalid_samples,
            )
        return sanitized

    def _history_and_current(self, series: List[Tuple[date, float]], current: date):
        usable = [(d, v) for d, v in series if d <= current]
        if not usable:
            raise ValueError("No macro data available for requested date")

        values = [v for _, v in usable]
        if len(values) == 1:
            # percentile計算を安定させるため、履歴が1件のときは同値を追加
            values.append(values[0])
        history = values[:-1]
        current_val = values[-1]
        return history, current_val

    def _calculate_scores(
        self,
        price_history: List[Tuple[str, float]],
        macro_series: Dict[str, List[Tuple[date, float]]],
        current_date: date,
        score_ma: int,
    ):
        technical_score, _ = calculate_technical_score(price_history, base_window=score_ma)

        r_hist, r_cur = self._history_and_current(macro_series["r_10y"], current_date)
        cpi_hist, cpi_cur = self._history_and_current(macro_series["cpi"], current_date)
        vix_hist, vix_cur = self._history_and_current(macro_series["vix"], current_date)

        macro_score, _ = calculate_macro_score(
            (r_hist, r_cur), (cpi_hist, cpi_cur), (vix_hist, vix_cur)
        )

        events = self.event_service.get_events_for_date(current_date)
        event_adjustment, _ = calculate_event_adjustment(current_date, events)

        ma500, ma1000 = calculate_ultra_long_mas(price_history)
        trend = calculate_ultra_long_trend_context(price_history)
        current_price = price_history[-1][1] if price_history else None
        total = calculate_total_score(
            technical_score,
            macro_score,
            event_adjustment,
            current_price=current_price,
            ma500=ma500,
            ma1000=ma1000,
            ma50=trend.get("ma50"),
            ma200=trend.get("ma200"),
            ma50_slope=trend.get("ma50_slope"),
            ma200_slope=trend.get("ma200_slope"),
        )
        return total

    def _compute_max_drawdown(self, values: List[float]) -> float:
        peak = values[0]
        max_dd = 0.0
        for v in values:
            if v > peak:
                peak = v
            dd = (peak - v) / peak if peak != 0 else 0
            if dd > max_dd:
                max_dd = dd
        return round(max_dd * 100, 2)

    def run_backtest(
        self,
        start_date: date,
        end_date: date,
        initial_cash: float,
        buy_threshold: float = 40.0,
        sell_threshold: float = 80.0,
        index_type: str = "SP500",
        score_ma: int = 200,
    ) -> Dict:
        initial_cash_safe = self._safe_float(initial_cash, field_name="initial_cash")
        buy_threshold_safe = self._safe_float(buy_threshold, field_name="buy_threshold")
        sell_threshold_safe = self._safe_float(sell_threshold, field_name="sell_threshold")
        if initial_cash_safe <= 0:
            raise ValueError("invalid_initial_cash:must_be_positive")
        if score_ma < 2:
            raise ValueError("invalid_score_ma:must_be_at_least_2")

        raw_price_history = self.market_service.get_price_history_range(
            start_date, end_date, allow_fallback=self.allow_fallback, index_type=index_type
        )
        price_history = self._prepare_price_history(raw_price_history, index_type)
        required_points = max(200, score_ma)
        if len(price_history) < required_points:
            raise ValueError(
                f"Not enough price history to run backtest (need >= {required_points} days)"
            )

        macro_series = self.macro_service.get_macro_series_range(start_date, end_date)

        cash = initial_cash_safe
        shares = 0
        portfolio_history: List[Dict] = []
        trades: List[Dict] = []
        score_rows = 0
        valid_score_rows = 0
        buy_threshold_hit_days = 0
        sell_threshold_hit_days = 0
        buy_signal_count = 0
        sell_signal_count = 0
        score_min: float | None = None
        score_max: float | None = None
        buy_filled_dates: List[str] = []
        warning_episode_active = False
        current_holding_days = 0
        holding_days_log: List[int] = []
        sell_cooldown_days = 5
        last_sell_idx: int | None = None
        yearly_trade_counts: Dict[int, int] = {}
        position_entry_price: float | None = None
        position_peak_price: float | None = None
        max_runup_pct = 0.0
        trailing_exit_count = 0
        trailing_partial_exit_count = 0
        realized_profit_amount = 0.0
        peak_profit_amount = 0.0
        reentry_count = 0
        missed_trend_count = 0
        breakdown_streak = 0

        hold_cash = initial_cash_safe
        hold_shares = 0
        first_price = price_history[0][1]
        hold_shares = floor(hold_cash / first_price)
        hold_cash -= hold_shares * first_price
        buy_hold_history: List[Dict] = []

        for idx, (date_str, close) in enumerate(price_history):
            current_dt = date.fromisoformat(date_str)

            if idx >= max(score_ma - 1, 199):
                sub_history = price_history[: idx + 1]
                score_rows += 1
                score = self._calculate_scores(sub_history, macro_series, current_dt, score_ma)
                score = self._safe_float(score, field_name="score")
                valid_score_rows += 1
                if score_min is None or score < score_min:
                    score_min = score
                if score_max is None or score > score_max:
                    score_max = score
                if score < buy_threshold_safe:
                    buy_threshold_hit_days += 1
                if score >= sell_threshold_safe:
                    sell_threshold_hit_days += 1

                technical_details = {}
                try:
                    _, technical_details = calculate_technical_score(sub_history, base_window=score_ma)
                except Exception:
                    technical_details = {}
                ma50_for_breakdown = float(technical_details.get("ma50_for_breakdown") or close)
                ma200_for_breakdown = float(technical_details.get("ma200_for_breakdown") or close)
                ma50_slope = technical_details.get("ma50_slope")
                price_below_ma50 = close < ma50_for_breakdown
                strong_uptrend = bool(technical_details.get("strong_uptrend"))
                trend_break = (
                    close < ma200_for_breakdown
                    and ma50_for_breakdown < ma200_for_breakdown
                    and (ma50_slope is not None and float(ma50_slope) <= 0.0)
                    and price_below_ma50
                )
                breakdown_streak = breakdown_streak + 1 if trend_break else 0
                breakdown_confirmed = breakdown_streak >= 2
                trade_year = current_dt.year
                yearly_trade_count = yearly_trade_counts.get(trade_year, 0)

                if shares > 0:
                    current_holding_days += 1
                    if position_peak_price is None:
                        position_peak_price = close
                    else:
                        position_peak_price = max(position_peak_price, close)
                    if position_entry_price is not None and position_entry_price > 0:
                        runup = (close - position_entry_price) / position_entry_price
                        max_runup_pct = max(max_runup_pct, runup * 100.0)
                trend_reentry_signal = (
                    close > ma200_for_breakdown
                    and (ma50_slope is not None and float(ma50_slope) > 0.0)
                )
                trend_stack_confirmed = ma50_for_breakdown > ma200_for_breakdown

                if shares > 0 and breakdown_confirmed and not strong_uptrend:
                    qty = shares
                    cash += qty * close
                    sell_signal_count += 1
                    trades.append(
                        {"action": "SELL", "mode": "full_exit", "date": date_str, "quantity": qty, "price": close}
                    )
                    if position_entry_price is not None and position_peak_price is not None:
                        realized_profit_amount += qty * (close - position_entry_price)
                        peak_profit_amount += qty * (position_peak_price - position_entry_price)
                    yearly_trade_counts[trade_year] = yearly_trade_count + 1
                    last_sell_idx = idx
                    shares = 0
                    warning_episode_active = False
                    holding_days_log.append(current_holding_days)
                    current_holding_days = 0
                    position_entry_price = None
                    position_peak_price = None
                if shares == 0 and trend_reentry_signal:
                    qty = floor(cash / close)
                    if qty > 0:
                        cash -= qty * close
                        shares += qty
                        buy_signal_count += 1
                        buy_filled_dates.append(date_str)
                        buy_mode = "reentry_trend" if trend_stack_confirmed else "reentry_trend_early"
                        trades.append(
                            {"action": "BUY", "mode": buy_mode, "date": date_str, "quantity": qty, "price": close}
                        )
                        current_holding_days = 0
                        warning_episode_active = False
                        position_entry_price = close
                        position_peak_price = close
                        reentry_count += 1

            portfolio_value = cash + shares * close
            portfolio_history.append({"date": date_str, "value": round(portfolio_value, 2)})

            hold_value = hold_cash + hold_shares * close
            buy_hold_history.append({"date": date_str, "value": round(hold_value, 2)})

        final_price = price_history[-1][1]
        final_value = cash + shares * final_price
        buy_hold_final = hold_cash + hold_shares * final_price

        logger.info(
            "[backtest] index_type=%s final_value_precheck=%s buy_hold_precheck=%s final_price=%s trades=%d",
            index_type,
            final_value,
            buy_hold_final,
            final_price,
            len(trades),
        )

        final_value = self._safe_float(final_value, field_name="final_value")
        buy_hold_final = self._safe_float(buy_hold_final, field_name="buy_and_hold_final")
        total_return = (final_value / initial_cash_safe) - 1
        days = (date.fromisoformat(price_history[-1][0]) - date.fromisoformat(price_history[0][0])).days
        years = days / 365.0 if days > 0 else 1
        cagr = (final_value / initial_cash_safe) ** (1 / years) - 1

        max_dd = self._compute_max_drawdown([p["value"] for p in portfolio_history])
        max_dd = self._safe_float(max_dd, field_name="max_drawdown_pct")
        buy_hold_max_dd = self._compute_max_drawdown([p["value"] for p in buy_hold_history])
        buy_hold_max_dd = self._safe_float(buy_hold_max_dd, field_name="buy_hold_max_drawdown_pct")
        if shares > 0 and current_holding_days > 0:
            holding_days_log.append(current_holding_days)
        average_holding_days = (
            round(sum(holding_days_log) / len(holding_days_log), 2) if holding_days_log else 0.0
        )
        max_drawdown_improvement = round(buy_hold_max_dd - max_dd, 2)
        realized_trade_count = max(1, sell_signal_count)
        profit_per_trade = round((final_value - initial_cash_safe) / realized_trade_count, 2)
        yearly_trade_count_max = max(yearly_trade_counts.values()) if yearly_trade_counts else 0
        trailing_exit_rate = round((trailing_exit_count / sell_signal_count), 4) if sell_signal_count > 0 else 0.0
        trailing_partial_exit_rate = round((trailing_partial_exit_count / sell_signal_count), 4) if sell_signal_count > 0 else 0.0
        trend_capture_rate = round((realized_profit_amount / peak_profit_amount), 4) if peak_profit_amount > 0 else 0.0
        missed_trend_rate = round(
            (missed_trend_count / (reentry_count + missed_trend_count)),
            4,
        ) if (reentry_count + missed_trend_count) > 0 else 0.0
        entered_market_once = buy_signal_count > 0
        in_position = shares > 0
        final_trade_count = len(trades)
        diagnosis = "normal"
        if valid_score_rows == 0:
            diagnosis = "score_generation_broken_or_missing"
        elif buy_signal_count > 0 and final_trade_count == 0:
            diagnosis = "signal_execution_divergence"
        elif buy_signal_count == 0 and sell_signal_count == 0:
            if buy_threshold_hit_days == 0 and sell_threshold_hit_days == 0:
                diagnosis = "score_outside_threshold_band_or_stuck"
            elif buy_threshold_hit_days > 0:
                diagnosis = "buy_threshold_hit_but_no_executable_qty_or_data_issue"
            else:
                diagnosis = "threshold_setting_or_signal_transition_issue"
        if buy_signal_count > 0 and final_trade_count == 0:
            logger.warning(
                "[backtest-signals-divergence] index_type=%s buy_signal_count=%d final_trade_count=%d in_position=%s buy_filled_dates=%s",
                index_type,
                buy_signal_count,
                final_trade_count,
                in_position,
                buy_filled_dates,
            )
        logger.info(
            "[backtest-signals] index_type=%s total_price_rows=%d total_score_rows=%d valid_score_rows=%d "
            "buy_threshold_hit_days=%d sell_threshold_hit_days=%d buy_signal_count=%d sell_signal_count=%d "
            "final_trade_count=%d entered_market_once=%s in_position=%s buy_filled_dates=%s score_min=%s score_max=%s diagnosis=%s",
            index_type,
            len(price_history),
            score_rows,
            valid_score_rows,
            buy_threshold_hit_days,
            sell_threshold_hit_days,
            buy_signal_count,
            sell_signal_count,
            final_trade_count,
            entered_market_once,
            in_position,
            buy_filled_dates,
            score_min,
            score_max,
            diagnosis,
        )

        return {
            "final_value": round(final_value, 2),
            "buy_and_hold_final": round(buy_hold_final, 2),
            "total_return_pct": round(total_return * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": max_dd,
            "buy_hold_max_drawdown_pct": buy_hold_max_dd,
            "max_drawdown_improvement_pct": max_drawdown_improvement,
            "trade_count": len(trades),
            "average_holding_days": average_holding_days,
            "profit_per_trade": profit_per_trade,
            "max_runup_pct": round(max_runup_pct, 2),
            "trailing_exit_rate": trailing_exit_rate,
            "trailing_partial_exit_rate": trailing_partial_exit_rate,
            "trend_capture_rate": trend_capture_rate,
            "reentry_count": reentry_count,
            "missed_trend_rate": missed_trend_rate,
            "trades": trades,
            "portfolio_history": portfolio_history,
            "buy_hold_history": buy_hold_history,
            "price_history": price_history,
            "diagnostics": {
                "index_type": index_type,
                "total_price_rows": len(price_history),
                "total_score_rows": score_rows,
                "valid_score_rows": valid_score_rows,
                "buy_threshold_hit_days": buy_threshold_hit_days,
                "sell_threshold_hit_days": sell_threshold_hit_days,
                "buy_signal_count": buy_signal_count,
                "sell_signal_count": sell_signal_count,
                "final_trade_count": final_trade_count,
                "entered_market_once": entered_market_once,
                "in_position": in_position,
                "buy_filled_dates": buy_filled_dates,
                "score_min": score_min,
                "score_max": score_max,
                "diagnosis": diagnosis,
                "average_holding_days": average_holding_days,
                "buy_hold_max_drawdown_pct": buy_hold_max_dd,
                "max_drawdown_improvement_pct": max_drawdown_improvement,
                "profit_per_trade": profit_per_trade,
                "yearly_trade_count_max": yearly_trade_count_max,
                "max_runup_pct": round(max_runup_pct, 2),
                "trailing_exit_rate": trailing_exit_rate,
                "trailing_partial_exit_rate": trailing_partial_exit_rate,
                "trend_capture_rate": trend_capture_rate,
                "reentry_count": reentry_count,
                "missed_trend_rate": missed_trend_rate,
            },
        }
