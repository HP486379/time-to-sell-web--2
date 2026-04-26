from __future__ import annotations

from datetime import date
from math import floor
from typing import Dict, List, Tuple

import logging
import math
import os
from scoring.events import calculate_event_adjustment
from scoring.macro import calculate_macro_score
from scoring.technical import calculate_technical_score, calculate_ultra_long_mas, moving_average
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
        current_price = price_history[-1][1] if price_history else None
        total = calculate_total_score(
            technical_score,
            macro_score,
            event_adjustment,
            current_price=current_price,
            ma500=ma500,
            ma1000=ma1000,
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
        sell_gate_block_count = 0
        sell_reason_counts = {"breakdown": 0, "crash": 0}
        sell_events: List[Dict] = []
        sell_post_returns: List[Dict] = []
        max_no_sell_streak_days = 0
        no_sell_streak_days = 0
        score_min: float | None = None
        score_max: float | None = None
        buy_filled_dates: List[str] = []
        overheat_event_date: str | None = None
        overheat_event_consumed = False
        prev_overheat_state = False
        sell_cooldown_days_remaining = 0
        days_since_last_sell: int | None = None
        recent_scores: List[float] = []
        buy_reason_counts = {
            "initial_threshold": 0,
            "pattern_a": 0,
            "pattern_b": 0,
            "both": 0,
            "day60": 0,
        }

        hold_cash = initial_cash_safe
        hold_shares = 0
        first_price = price_history[0][1]
        hold_shares = floor(hold_cash / first_price)
        hold_cash -= hold_shares * first_price
        buy_hold_history: List[Dict] = []

        for idx, (date_str, close) in enumerate(price_history):
            current_dt = date.fromisoformat(date_str)
            no_sell_streak_days += 1
            if sell_cooldown_days_remaining > 0:
                sell_cooldown_days_remaining -= 1
            if days_since_last_sell is not None:
                days_since_last_sell += 1

            if idx >= max(score_ma - 1, 199):
                sub_history = price_history[: idx + 1]
                score_rows += 1
                score = self._calculate_scores(sub_history, macro_series, current_dt, score_ma)
                score = self._safe_float(score, field_name="score")
                closes = [p[1] for p in sub_history]
                ma20_series = moving_average(closes, 20)
                ma50_series = moving_average(closes, 50)
                ma200_series = moving_average(closes, 200)

                is_overheat_today = score >= sell_threshold_safe
                if is_overheat_today and not prev_overheat_state:
                    overheat_event_date = date_str
                    overheat_event_consumed = False
                prev_overheat_state = is_overheat_today

                recent_scores.append(score)
                score_declining_3days = (
                    len(recent_scores) >= 3
                    and recent_scores[-3] > recent_scores[-2] > recent_scores[-1]
                )
                ma50_falling_5days = len(ma50_series) >= 6 and ma50_series[-1] < ma50_series[-6]
                breakdown_sell = (
                    close < ma50_series[-1]
                    and ma50_falling_5days
                    and close < ma20_series[-1]
                    and close < ma200_series[-1]
                    and score_declining_3days
                )
                drop_10d = (
                    (close / closes[-11] - 1.0)
                    if len(closes) >= 11 and closes[-11] > 0
                    else None
                )
                drop_20d = (
                    (close / closes[-21] - 1.0)
                    if len(closes) >= 21 and closes[-21] > 0
                    else None
                )
                crash_sell = (
                    (drop_10d is not None and drop_10d <= -0.10)
                    or (drop_20d is not None and drop_20d <= -0.15)
                )
                strong_uptrend = ma20_series[-1] > ma50_series[-1] > ma200_series[-1]
                suppress_sell = score > 60 and strong_uptrend
                sell_breakdown_active = breakdown_sell and not suppress_sell
                sell_crash_active = crash_sell and not suppress_sell
                sell_gate_open = sell_breakdown_active or sell_crash_active
                sell_reason: str | None = None
                if sell_crash_active:
                    sell_reason = "crash"
                elif sell_breakdown_active:
                    sell_reason = "breakdown"
                cooldown_active = sell_cooldown_days_remaining > 0
                score_t2 = recent_scores[-3] if len(recent_scores) >= 3 else None
                score_t1 = recent_scores[-2] if len(recent_scores) >= 2 else None
                score_t0 = recent_scores[-1] if len(recent_scores) >= 1 else None
                score_delta_2 = (
                    (score_t0 - score_t2)
                    if score_t0 is not None and score_t2 is not None
                    else None
                )
                buy_reason: str | None = None
                if days_since_last_sell is None:
                    # 初回エントリーは従来閾値を利用
                    buy_gate_open = score < buy_threshold_safe
                    if buy_gate_open:
                        buy_reason = "initial_threshold"
                elif days_since_last_sell < 20:
                    buy_gate_open = False
                elif days_since_last_sell < 60:
                    pattern_a = close > ma20_series[-1] and score > (buy_threshold_safe - 5.0)
                    pattern_b = (
                        len(recent_scores) >= 3
                        and recent_scores[-3] < recent_scores[-2] < recent_scores[-1]
                    )
                    buy_gate_open = pattern_a or pattern_b
                    if buy_gate_open:
                        if pattern_a and pattern_b:
                            buy_reason = "both"
                        elif pattern_a:
                            buy_reason = "pattern_a"
                        else:
                            buy_reason = "pattern_b"
                else:
                    buy_gate_open = True
                    buy_reason = "day60"
                valid_score_rows += 1
                if score_min is None or score < score_min:
                    score_min = score
                if score_max is None or score > score_max:
                    score_max = score
                if score < buy_threshold_safe:
                    buy_threshold_hit_days += 1
                if score >= sell_threshold_safe:
                    sell_threshold_hit_days += 1

                if shares > 0 and sell_gate_open and not cooldown_active:
                    cash += shares * close
                    sell_signal_count += 1
                    if sell_reason in sell_reason_counts:
                        sell_reason_counts[sell_reason] += 1
                    sell_events.append(
                        {
                            "date": date_str,
                            "index_type": index_type,
                            "reason": sell_reason,
                            "price": round(close, 4),
                            "score": round(score, 4),
                            "drawdown_10d_pct": round((drop_10d or 0.0) * 100, 4),
                            "drawdown_20d_pct": round((drop_20d or 0.0) * 100, 4),
                            "_row_index": idx,
                        }
                    )
                    trades.append(
                        {
                            "action": "SELL",
                            "date": date_str,
                            "quantity": shares,
                            "price": close,
                            "reason": sell_reason,
                        }
                    )
                    shares = 0
                    overheat_event_consumed = True
                    sell_cooldown_days_remaining = 30
                    days_since_last_sell = 0
                    if no_sell_streak_days > max_no_sell_streak_days:
                        max_no_sell_streak_days = no_sell_streak_days
                    no_sell_streak_days = 0
                elif shares > 0 and (sell_gate_open and cooldown_active):
                    sell_gate_block_count += 1
                elif shares == 0 and buy_gate_open:
                    qty = floor(cash / close)
                    if qty > 0:
                        cash -= qty * close
                        shares += qty
                        buy_signal_count += 1
                        if buy_reason in buy_reason_counts:
                            buy_reason_counts[buy_reason] += 1
                        buy_filled_dates.append(date_str)
                        logger.info(
                            "[buy-trigger] date=%s reason=%s days_since_last_sell=%s score_t-2=%s score_t-1=%s score_t=%s delta_2=%s",
                            date_str,
                            buy_reason,
                            days_since_last_sell,
                            score_t2,
                            score_t1,
                            score_t0,
                            score_delta_2,
                        )
                        trades.append(
                            {
                                "action": "BUY",
                                "date": date_str,
                                "quantity": qty,
                                "price": close,
                                "reason": buy_reason,
                            }
                        )

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
        max_no_sell_streak_days = max(max_no_sell_streak_days, no_sell_streak_days)
        for event in sell_events:
            row_idx = int(event.pop("_row_index"))
            price_now = price_history[row_idx][1]
            return_5d_pct = None
            return_20d_pct = None
            if row_idx + 5 < len(price_history):
                return_5d_pct = round(((price_history[row_idx + 5][1] / price_now) - 1.0) * 100, 4)
            if row_idx + 20 < len(price_history):
                return_20d_pct = round(((price_history[row_idx + 20][1] / price_now) - 1.0) * 100, 4)
            sell_post_returns.append(
                {
                    "date": event["date"],
                    "reason": event["reason"],
                    "return_5d_pct": return_5d_pct,
                    "return_20d_pct": return_20d_pct,
                }
            )
        sell_to_buy_wait_days: List[int] = []
        last_sell_dt: date | None = None
        for trade in trades:
            trade_dt = date.fromisoformat(trade["date"])
            if trade["action"] == "SELL":
                last_sell_dt = trade_dt
            elif trade["action"] == "BUY" and last_sell_dt is not None:
                wait_days = (trade_dt - last_sell_dt).days
                if wait_days >= 0:
                    sell_to_buy_wait_days.append(wait_days)
                last_sell_dt = None
        early_buy_count = (
            buy_reason_counts.get("pattern_a", 0)
            + buy_reason_counts.get("pattern_b", 0)
            + buy_reason_counts.get("both", 0)
        )
        post_sell_buy_count = early_buy_count + buy_reason_counts.get("day60", 0)
        early_buy_ratio = (
            round((early_buy_count / post_sell_buy_count) * 100, 2) if post_sell_buy_count > 0 else 0.0
        )
        avg_cash_wait_days = (
            round(sum(sell_to_buy_wait_days) / len(sell_to_buy_wait_days), 2)
            if sell_to_buy_wait_days
            else None
        )
        max_cash_wait_days = max(sell_to_buy_wait_days) if sell_to_buy_wait_days else None
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
            "final_trade_count=%d entered_market_once=%s in_position=%s buy_filled_dates=%s score_min=%s score_max=%s "
            "sell_gate_block_count=%d early_buy_ratio_pct=%s avg_cash_wait_days=%s max_cash_wait_days=%s diagnosis=%s",
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
            sell_gate_block_count,
            early_buy_ratio,
            avg_cash_wait_days,
            max_cash_wait_days,
            diagnosis,
        )
        logger.info(
            "[backtest-sell-summary] index_type=%s total_sell=%d breakdown=%d crash=%d max_no_sell_streak_days=%d",
            index_type,
            sell_signal_count,
            sell_reason_counts.get("breakdown", 0),
            sell_reason_counts.get("crash", 0),
            max_no_sell_streak_days,
        )
        if sell_signal_count == 0:
            logger.info("[backtest-sell-summary] index_type=%s NO SELL TRIGGERED", index_type)

        return {
            "final_value": round(final_value, 2),
            "buy_and_hold_final": round(buy_hold_final, 2),
            "total_return_pct": round(total_return * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": max_dd,
            "trade_count": len(trades),
            "trades": trades,
            "portfolio_history": portfolio_history,
            "buy_hold_history": buy_hold_history,
            "price_history": price_history,
            "sell_count_by_reason": sell_reason_counts,
            "diagnostics": {
                "index_type": index_type,
                "total_price_rows": len(price_history),
                "total_score_rows": score_rows,
                "valid_score_rows": valid_score_rows,
                "buy_threshold_hit_days": buy_threshold_hit_days,
                "sell_threshold_hit_days": sell_threshold_hit_days,
                "buy_signal_count": buy_signal_count,
                "sell_signal_count": sell_signal_count,
                "sell_gate_block_count": sell_gate_block_count,
                "sell_reason_counts": sell_reason_counts,
                "sell_events": sell_events,
                "sell_post_returns": sell_post_returns,
                "max_no_sell_streak_days": max_no_sell_streak_days,
                "final_trade_count": final_trade_count,
                "entered_market_once": entered_market_once,
                "in_position": in_position,
                "buy_filled_dates": buy_filled_dates,
                "buy_reason_counts": buy_reason_counts,
                "early_buy_ratio_pct": early_buy_ratio,
                "avg_cash_wait_days": avg_cash_wait_days,
                "max_cash_wait_days": max_cash_wait_days,
                "score_min": score_min,
                "score_max": score_max,
                "diagnosis": diagnosis,
            },
        }
