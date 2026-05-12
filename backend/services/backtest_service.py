from __future__ import annotations

from datetime import date
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import time
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

INDEX_SELL_RULE_MAP = {
    "SP500_JPY": "ath_boost_8_score80_gate",
    "ALLCOUNTRY_JPY": "no_ath_penalty_score80_gate",
    "TOPIX": "topix_overheat_guard_score80_gate",
    "NIKKEI225": "nikkei225_trend_break_guard_score80_gate",
}


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

    def _get_sell_rule_name(self, index_type: str) -> str:
        return INDEX_SELL_RULE_MAP.get(index_type, "current_logic")

    def _apply_technical_sell_variant(self, rule_name: str, technical_score: float, closes: List[float]) -> float:
        adjusted = technical_score
        is_60d_high = len(closes) >= 60 and closes[-1] >= max(closes[-60:])
        if rule_name == "ath_boost_8_score80_gate" and is_60d_high:
            adjusted += 8.0
        if rule_name == "no_ath_penalty_score80_gate" and is_60d_high:
            adjusted += 12.0
        return max(0.0, min(100.0, float(adjusted)))

    def _topix_overheat_guard_boost(self, closes: List[float], ma20: float, ma60: float, ma200: float) -> float:
        if len(closes) < 120:
            return 0.0
        close = closes[-1]
        if not (close > ma20 and close > ma60 and close > ma200):
            return 0.0
        max_60 = max(closes[-60:])
        max_120 = max(closes[-120:])
        is_near_60d_high = close >= max_60 * 0.992
        is_near_120d_high = close >= max_120 * 0.992
        prev20 = closes[-21] if len(closes) >= 21 else None
        prev60 = closes[-61] if len(closes) >= 61 else None
        if prev20 is None or prev60 is None or prev20 <= 0 or prev60 <= 0:
            return 0.0
        return_20d_before = ((close / prev20) - 1.0) * 100.0
        return_60d_before = ((close / prev60) - 1.0) * 100.0
        dev20 = ((close / ma20) - 1.0) * 100.0 if ma20 > 0 else 0.0
        dev60 = ((close / ma60) - 1.0) * 100.0 if ma60 > 0 else 0.0
        base_ok = (
            is_near_60d_high
            and is_near_120d_high
            and return_20d_before >= 6.0
            and return_60d_before >= 5.0
        )
        if not base_ok:
            return 0.0
        boost = 20.0
        if dev20 >= 4.0 and dev60 >= 5.0:
            boost += 15.0
        return boost



    def _nikkei225_trend_break_guard_boost(self, closes: List[float], ma20: float, ma60: float, ma200: float) -> tuple[float, bool]:
        if len(closes) < 120:
            return 0.0, False
        close = closes[-1]
        if not (close > ma60 and close > ma200):
            return 0.0, False
        max_60 = max(closes[-60:])
        max_120 = max(closes[-120:])
        is_near_60d_high = close >= max_60 * 0.992
        is_near_120d_high = close >= max_120 * 0.992
        if not (is_near_60d_high and is_near_120d_high):
            return 0.0, False

        prev20 = closes[-21] if len(closes) >= 21 else None
        prev60 = closes[-61] if len(closes) >= 61 else None
        prev5 = closes[-6] if len(closes) >= 6 else None
        prev3 = closes[-4] if len(closes) >= 4 else None
        if any(v is None or v <= 0 for v in [prev20, prev60, prev5, prev3]):
            return 0.0, False

        return_20d_before = ((close / prev20) - 1.0) * 100.0
        return_60d_before = ((close / prev60) - 1.0) * 100.0
        return_5d = ((close / prev5) - 1.0) * 100.0
        return_3d = ((close / prev3) - 1.0) * 100.0
        deviation_from_ma20_pct = ((close / ma20) - 1.0) * 100.0 if ma20 > 0 else 0.0
        deviation_from_ma60_pct = ((close / ma60) - 1.0) * 100.0 if ma60 > 0 else 0.0
        recent_10d_high = max(closes[-10:]) if len(closes) >= 10 else close
        recent_3d_high = max(closes[-3:]) if len(closes) >= 3 else close

        overheat_count = sum([
            return_20d_before >= 6.0,
            return_60d_before >= 5.0,
            deviation_from_ma20_pct >= 4.0,
            deviation_from_ma60_pct >= 5.0,
        ])
        trend_break_count = sum([
            close < ma20,
            close <= recent_10d_high * 0.97,
            return_5d <= -2.0,
            close < recent_3d_high,
            return_3d <= -1.0,
        ])

        if overheat_count < 2:
            return 0.0, False
        trend_break_ok = trend_break_count >= 2
        if not trend_break_ok:
            return 0.0, False

        boost = 30.0
        if close < ma20 and return_5d <= -2.0 and close <= recent_10d_high * 0.97:
            boost += 10.0
        return boost, True
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


    def _build_trade_pair_diagnostics(self, trades: List[Dict], price_history: List[Tuple[str, float]]) -> List[Dict]:
        index_by_date = {dt: idx for idx, (dt, _) in enumerate(price_history)}
        details: List[Dict] = []
        sell_trades = [t for t in trades if t.get("action") == "SELL"]
        for trade_no, sell in enumerate(sell_trades, start=1):
            sell_idx = index_by_date.get(sell["date"])
            if sell_idx is None:
                continue
            next_buy = next((t for t in trades[trades.index(sell) + 1 :] if t.get("action") == "BUY"), None)
            buy_idx = index_by_date.get(next_buy["date"]) if next_buy else None
            end_idx = buy_idx if buy_idx is not None else len(price_history) - 1
            window = price_history[sell_idx : end_idx + 1]
            min_row = min(window, key=lambda x: x[1]) if window else price_history[sell_idx]
            min_idx = index_by_date.get(min_row[0], sell_idx)
            sell_price = float(sell["price"])
            buy_price = float(next_buy["price"]) if next_buy else None
            days_out = (
                (date.fromisoformat(next_buy["date"]) - date.fromisoformat(sell["date"])).days
                if next_buy
                else None
            )
            sell_to_buy_return_pct = (
                round(((buy_price / sell_price) - 1.0) * 100.0, 4) if buy_price is not None and sell_price > 0 else None
            )
            max_dd_after_sell_pct = round(((min_row[1] / sell_price) - 1.0) * 100.0, 4) if sell_price > 0 else None
            rebound_from_bottom_to_buy_pct = (
                round(((buy_price / min_row[1]) - 1.0) * 100.0, 4)
                if buy_price is not None and min_row[1] > 0
                else None
            )
            timing_eval = "unclear"
            if buy_idx is not None:
                days_from_bottom = (date.fromisoformat(next_buy["date"]) - date.fromisoformat(min_row[0])).days
                if days_from_bottom <= 5 and (rebound_from_bottom_to_buy_pct or 0.0) <= 3.0:
                    timing_eval = "buy_early_or_good"
                elif days_from_bottom >= 15 and (rebound_from_bottom_to_buy_pct or 0.0) >= 5.0:
                    timing_eval = "buy_late"
                else:
                    timing_eval = "buy_neutral"

            fwd = {}
            for d in [5, 10, 20, 40]:
                if sell_idx + d < len(price_history) and sell_price > 0:
                    fwd[f"sell_forward_{d}d_return_pct"] = round(((price_history[sell_idx + d][1] / sell_price) - 1.0) * 100.0, 4)
                else:
                    fwd[f"sell_forward_{d}d_return_pct"] = None

            contribution = "unknown"
            if sell_to_buy_return_pct is not None:
                contribution = "improved_vs_hold" if sell_to_buy_return_pct < 0 else "worsened_vs_hold"

            details.append(
                {
                    "trade_no": trade_no,
                    "sell_date": sell["date"],
                    "sell_price": sell_price,
                    "sell_reason": sell.get("reason"),
                    "buy_date": next_buy["date"] if next_buy else None,
                    "buy_price": buy_price,
                    "buy_reason": next_buy.get("reason") if next_buy else None,
                    "days_out_of_market": days_out,
                    "sell_to_buy_return_pct": sell_to_buy_return_pct,
                    **fwd,
                    "min_after_sell_date": min_row[0],
                    "min_after_sell_price": min_row[1],
                    "max_drawdown_after_sell_pct": max_dd_after_sell_pct,
                    "days_to_min_after_sell": (date.fromisoformat(min_row[0]) - date.fromisoformat(sell["date"])).days,
                    "buy_timing_assessment": timing_eval,
                    "trade_contribution_assessment": contribution,
                    "rebound_from_bottom_to_buy_pct": rebound_from_bottom_to_buy_pct,
                }
            )
        return details

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

        fetch_timeout_sec = float(os.getenv("BACKTEST_PRICE_FETCH_TIMEOUT_SEC", "120"))
        t0_fetch = time.monotonic()
        logger.info(
            "[backtest] price_fetch_start index_type=%s requested_start=%s requested_end=%s timeout_sec=%s",
            index_type,
            start_date.isoformat(),
            end_date.isoformat(),
            fetch_timeout_sec,
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(
                    self.market_service.get_price_history_range,
                    start_date,
                    end_date,
                    self.allow_fallback,
                    index_type,
                )
                raw_price_history = fut.result(timeout=fetch_timeout_sec)
        except FuturesTimeoutError as exc:
            raise ValueError(
                "price_history_fetch_timeout:"
                f"index_type={index_type},requested_start={start_date.isoformat()},end_date={end_date.isoformat()}"
            ) from exc
        finally:
            logger.info(
                "[backtest] price_fetch_end index_type=%s elapsed_sec=%.3f",
                index_type,
                time.monotonic() - t0_fetch,
            )
        price_history = self._prepare_price_history(raw_price_history, index_type)
        requested_start_iso = start_date.isoformat()
        if price_history:
            first_available = date.fromisoformat(price_history[0][0])
            logger.info("[backtest] available_start index_type=%s requested_start=%s available_start=%s", index_type, requested_start_iso, first_available.isoformat())
            if first_available > start_date and (first_available - start_date).days > 10:
                raise ValueError(
                    "insufficient_history_for_requested_start:"
                    f"requested_start={requested_start_iso},first_available={first_available.isoformat()}"
                )

        required_points = max(200, score_ma)
        if len(price_history) < required_points:
            raise ValueError(
                f"Not enough price history to run backtest (need >= {required_points} days)"
            )

        macro_series = self.macro_service.get_macro_series_range(start_date, end_date)

        first_price = price_history[0][1]
        initial_shares = floor(initial_cash_safe / first_price)
        initial_cash_after_buy = initial_cash_safe - (initial_shares * first_price)
        cash = initial_cash_after_buy
        shares = initial_shares
        portfolio_history: List[Dict] = []
        trades: List[Dict] = []
        score_rows = 0
        valid_score_rows = 0
        buy_threshold_hit_days = 0
        sell_threshold_hit_days = 0
        buy_signal_count = 0
        sell_signal_count = 0
        sell_gate_block_count = 0
        score_min: float | None = None
        score_max: float | None = None
        buy_filled_dates: List[str] = []
        overheat_event_date: str | None = None
        overheat_event_consumed = False
        prev_overheat_state = False
        sell_cooldown_days_remaining = 0
        days_since_last_sell: int | None = None
        recent_scores: List[float] = []
        last_sell_reason: str | None = None
        buy_reason_counts = {
            "initial_threshold": 0,
            "pattern_a": 0,
            "pattern_b": 0,
            "both": 0,
            "day60": 0,
        }
        daily_scores: List[Dict] = []
        trade_enriched_rows: List[Dict] = []

        hold_cash = initial_cash_safe
        hold_shares = 0
        hold_shares = floor(hold_cash / first_price)
        hold_cash -= hold_shares * first_price
        buy_hold_history: List[Dict] = []

        for idx, (date_str, close) in enumerate(price_history):
            current_dt = date.fromisoformat(date_str)
            if sell_cooldown_days_remaining > 0:
                sell_cooldown_days_remaining -= 1
            if days_since_last_sell is not None:
                days_since_last_sell += 1

            if idx >= max(score_ma - 1, 199):
                sub_history = price_history[: idx + 1]
                score_rows += 1
                score = self._calculate_scores(sub_history, macro_series, current_dt, score_ma)
                score = self._safe_float(score, field_name="score")
                daily_scores.append({"date": date_str, "score": score})
                closes = [p[1] for p in sub_history]
                sell_rule_name = self._get_sell_rule_name(index_type)
                if sell_rule_name != "current_logic":
                    technical_score, _ = calculate_technical_score(sub_history, base_window=score_ma)
                    technical_score = self._apply_technical_sell_variant(sell_rule_name, technical_score, closes)
                    r_hist, r_cur = self._history_and_current(macro_series["r_10y"], current_dt)
                    cpi_hist, cpi_cur = self._history_and_current(macro_series["cpi"], current_dt)
                    vix_hist, vix_cur = self._history_and_current(macro_series["vix"], current_dt)
                    macro_score, _ = calculate_macro_score((r_hist, r_cur), (cpi_hist, cpi_cur), (vix_hist, vix_cur))
                    events = self.event_service.get_events_for_date(current_dt)
                    event_adjustment, _ = calculate_event_adjustment(current_dt, events)
                    ma500, ma1000 = calculate_ultra_long_mas(sub_history)
                    score = calculate_total_score(
                        technical_score,
                        macro_score,
                        event_adjustment,
                        current_price=close,
                        ma500=ma500,
                        ma1000=ma1000,
                    )
                ma20_series = moving_average(closes, 20)
                ma50_series = moving_average(closes, 50)
                ma60_series = moving_average(closes, 60)
                ma200_series = moving_average(closes, 200)

                is_overheat_today = score >= sell_threshold_safe
                if is_overheat_today and not prev_overheat_state:
                    overheat_event_date = date_str
                    overheat_event_consumed = False
                prev_overheat_state = is_overheat_today

                recent_scores.append(score)
                score_declining_3days = (
                    len(recent_scores) >= 4
                    and recent_scores[-1] < recent_scores[-2] < recent_scores[-3] < recent_scores[-4]
                )
                close_below_ma20 = close < ma20_series[-1]
                peakout_detected = score_declining_3days and close_below_ma20

                close_below_ma20_2days = (
                    len(closes) >= 2
                    and close < ma20_series[-1]
                    and closes[-2] < ma20_series[-2]
                )
                close_below_ma50 = close < ma50_series[-1]
                confirmation_detected = close_below_ma20_2days or close_below_ma50

                overheat_event_active = overheat_event_date is not None and not overheat_event_consumed
                sell_gate_open = overheat_event_active and peakout_detected and confirmation_detected
                topix_overheat_guard_active = False
                nikkei225_trend_break_guard_active = False
                nikkei225_trend_break_guard_blocked_no_trend_break = False
                if sell_rule_name in {"ath_boost_8_score80_gate", "no_ath_penalty_score80_gate"}:
                    sell_gate_open = shares > 0 and score >= sell_threshold_safe
                elif sell_rule_name == "topix_overheat_guard_score80_gate":
                    boost = self._topix_overheat_guard_boost(closes, ma20_series[-1], ma60_series[-1], ma200_series[-1])
                    if shares > 0 and boost > 0:
                        score = max(0.0, min(100.0, score + boost))
                        topix_overheat_guard_active = score >= sell_threshold_safe
                        if topix_overheat_guard_active:
                            sell_gate_open = True
                elif sell_rule_name == "nikkei225_trend_break_guard_score80_gate":
                    boost, trend_break_ok = self._nikkei225_trend_break_guard_boost(
                        closes,
                        ma20_series[-1],
                        ma60_series[-1],
                        ma200_series[-1],
                    )
                    if shares > 0:
                        if boost > 0:
                            score = max(0.0, min(100.0, score + boost))
                            nikkei225_trend_break_guard_active = score >= sell_threshold_safe and trend_break_ok
                            if nikkei225_trend_break_guard_active:
                                sell_gate_open = True
                        elif score >= sell_threshold_safe:
                            nikkei225_trend_break_guard_blocked_no_trend_break = True
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
                pattern_a = False
                pattern_b = False
                day60_condition = False
                score_threshold_condition = score < buy_threshold_safe
                nikkei_fast_buyback_enabled = (
                    index_type == "NIKKEI225"
                    and last_sell_reason is not None
                    and str(last_sell_reason).startswith("nikkei225_trend_break_guard")
                    and shares == 0
                )
                prev_close = closes[-2] if len(closes) >= 2 else close
                prev3 = closes[-4] if len(closes) >= 4 and closes[-4] > 0 else None
                prev5 = closes[-6] if len(closes) >= 6 and closes[-6] > 0 else None
                return_3d = ((close / prev3) - 1.0) * 100.0 if prev3 is not None else None
                return_5d = ((close / prev5) - 1.0) * 100.0 if prev5 is not None else None
                recent_10d_low = min(closes[-10:]) if len(closes) >= 10 else close
                rebound_from_10d_low = ((close / recent_10d_low) - 1.0) * 100.0 if recent_10d_low > 0 else 0.0
                recent_5d_high = max(closes[-5:]) if len(closes) >= 5 else close
                ma200_guard_ok = close >= (ma200_series[-1] * 0.97)

                if nikkei_fast_buyback_enabled and days_since_last_sell is not None and days_since_last_sell < 3:
                    buy_gate_open = False
                    buy_reason = "nikkei225_fast_buyback_blocked_too_early"
                elif nikkei_fast_buyback_enabled and days_since_last_sell is not None and not ma200_guard_ok:
                    buy_gate_open = False
                    buy_reason = "nikkei225_fast_buyback_blocked_below_ma200"
                elif nikkei_fast_buyback_enabled and days_since_last_sell is not None:
                    cond_a = close > ma20_series[-1] and (return_3d is not None and return_3d >= 0.0)
                    cond_b = (return_3d is not None and return_3d >= 2.0) and (return_5d is not None and return_5d >= 0.0)
                    cond_c = rebound_from_10d_low >= 4.0 and close > prev_close
                    cond_d = close >= recent_5d_high and (return_3d is not None and return_3d >= 0.0)
                    fast_buyback_open = cond_a or cond_b or cond_c or cond_d
                    if score_threshold_condition:
                        buy_gate_open = True
                        buy_reason = "initial_threshold"
                    elif days_since_last_sell >= 40 and fast_buyback_open:
                        buy_gate_open = True
                        buy_reason = (
                            "nikkei225_fast_buyback_ma20_recovery" if cond_a else
                            "nikkei225_fast_buyback_short_reversal" if cond_b else
                            "nikkei225_fast_buyback_bottom_rebound" if cond_c else
                            "nikkei225_fast_buyback_recent_high_recovery"
                        )
                    elif 3 <= days_since_last_sell < 40 and fast_buyback_open:
                        buy_gate_open = True
                        buy_reason = (
                            "nikkei225_fast_buyback_ma20_recovery" if cond_a else
                            "nikkei225_fast_buyback_short_reversal" if cond_b else
                            "nikkei225_fast_buyback_bottom_rebound" if cond_c else
                            "nikkei225_fast_buyback_recent_high_recovery"
                        )
                    else:
                        buy_gate_open = False
                elif days_since_last_sell is None:
                    # 初回エントリーは従来閾値を利用
                    buy_gate_open = score_threshold_condition
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
                    day60_condition = True
                rebound_detected = pattern_b
                confirmation_detected = pattern_a
                cooldown_clear_condition = (
                    days_since_last_sell is None or days_since_last_sell >= 20
                )
                valid_score_rows += 1
                if score_min is None or score < score_min:
                    score_min = score
                if score_max is None or score > score_max:
                    score_max = score
                if score < buy_threshold_safe:
                    buy_threshold_hit_days += 1
                if score >= sell_threshold_safe:
                    sell_threshold_hit_days += 1
                score_threshold_today = score >= sell_threshold_safe

                if shares > 0 and sell_gate_open and not cooldown_active and score_threshold_today:
                    sold_quantity = shares
                    cash += shares * close
                    sell_signal_count += 1
                    trades.append(
                        {
                            "action": "SELL",
                            "date": date_str,
                            "quantity": shares,
                            "price": close,
                            "reason": (
                                "topix_overheat_guard_bypass_peakout_confirmation"
                                if topix_overheat_guard_active
                                else "topix_overheat_guard_score80_gate"
                                if sell_rule_name == "topix_overheat_guard_score80_gate"
                                else "nikkei225_trend_break_guard_bypass_peakout_confirmation"
                                if nikkei225_trend_break_guard_active
                                else "nikkei225_trend_break_guard_blocked_no_trend_break"
                                if nikkei225_trend_break_guard_blocked_no_trend_break
                                else "nikkei225_trend_break_guard_score80_gate"
                                if sell_rule_name == "nikkei225_trend_break_guard_score80_gate"
                                else "current_logic_sell"
                            ),
                        }
                    )
                    trade_enriched_rows.append(
                        {
                            "action": "SELL",
                            "date": date_str,
                            "price": close,
                            "total_score": score,
                            "quantity": sold_quantity,
                            "portfolio_cash_after_sell": cash,
                            "score_threshold_today": score_threshold_today,
                            "overheat_event_active": overheat_event_active,
                            "peakout_detected": peakout_detected,
                            "confirmation_detected": confirmation_detected,
                            "sell_gate_open": sell_gate_open,
                            "cooldown_clear": not cooldown_active,
                        }
                    )
                    shares = 0
                    overheat_event_consumed = True
                    sell_cooldown_days_remaining = 30
                    days_since_last_sell = 0
                    last_sell_reason = trades[-1]["reason"]
                elif shares > 0 and (sell_gate_open and cooldown_active):
                    sell_gate_block_count += 1
                elif shares > 0 and overheat_event_active and not sell_gate_open:
                    sell_gate_block_count += 1
                elif shares == 0 and buy_gate_open:
                    qty = floor(cash / close)
                    if qty > 0:
                        cash_before_buy = cash
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
                        trade_enriched_rows.append(
                            {
                                "action": "BUY",
                                "date": date_str,
                                "price": close,
                                "total_score": score,
                                "quantity": qty,
                                "cash_before_buy": cash_before_buy,
                                "cash_after_buy": cash,
                                "score_threshold": score_threshold_condition,
                                "buy_gate_open": buy_gate_open,
                                "cooldown_clear": cooldown_clear_condition,
                                "pattern_a": pattern_a,
                                "pattern_b": pattern_b,
                                "day60": day60_condition,
                                "rebound_detected": rebound_detected,
                                "confirmation_detected": confirmation_detected,
                                "signal_reason": buy_reason,
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

        buy_trades = [trade for trade in trades if trade["action"] == "BUY"]
        sell_trades = [trade for trade in trades if trade["action"] == "SELL"]
        first_trade = trades[0] if trades else None
        last_trade = trades[-1] if trades else None
        first_signal_buy_trade = buy_trades[0] if buy_trades else None
        start_date_str = price_history[0][0] if price_history else None
        start_price = price_history[0][1] if price_history else None
        first_signal_buy_date_str = first_signal_buy_trade["date"] if first_signal_buy_trade else None
        first_signal_buy_price = first_signal_buy_trade["price"] if first_signal_buy_trade else None
        first_signal_buy_calendar_days = (
            (date.fromisoformat(first_signal_buy_date_str) - date.fromisoformat(start_date_str)).days
            if first_signal_buy_date_str and start_date_str
            else None
        )
        first_signal_buy_trading_days = (
            next((idx for idx, (dt, _) in enumerate(price_history) if dt == first_signal_buy_date_str), None)
            if first_signal_buy_date_str
            else None
        )
        missed_return_until_first_signal_buy_pct = (
            round(((first_signal_buy_price / start_price) - 1) * 100, 4)
            if first_signal_buy_price is not None and start_price is not None
            else None
        )

        buy_events: List[Dict] = []
        for idx, trade in enumerate(trade_enriched_rows):
            if trade["action"] != "BUY":
                continue
            buy_events.append(
                {
                    "date": trade["date"],
                    "price": trade["price"],
                    "total_score": trade["total_score"],
                    "buy_threshold": buy_threshold_safe,
                    "index_type": index_type,
                    "quantity": trade["quantity"],
                    "buy_reason": [
                        condition
                        for condition, enabled in [
                            ("score_threshold", trade.get("score_threshold", False)),
                            ("buy_gate_open", trade.get("buy_gate_open", False)),
                            ("cooldown_clear", trade.get("cooldown_clear", False)),
                            ("pattern_a", trade.get("pattern_a", False)),
                            ("pattern_b", trade.get("pattern_b", False)),
                            ("day60", trade.get("day60", False)),
                            ("rebound_detected", trade.get("rebound_detected", False)),
                            ("confirmation_detected", trade.get("confirmation_detected", False)),
                        ]
                        if enabled
                    ],
                    "buy_reason_flags": {
                        "score_threshold": trade.get("score_threshold", False),
                        "buy_gate_open": trade.get("buy_gate_open", False),
                        "cooldown_clear": trade.get("cooldown_clear", False),
                        "pattern_a": trade.get("pattern_a", False),
                        "pattern_b": trade.get("pattern_b", False),
                        "day60": trade.get("day60", False),
                        "rebound_detected": trade.get("rebound_detected", False),
                        "confirmation_detected": trade.get("confirmation_detected", False),
                        "signal_reason": trade.get("signal_reason"),
                    },
                    "is_initial_entry": False,
                    "cash_before_buy": round(trade["cash_before_buy"], 2),
                    "cash_after_buy": round(trade["cash_after_buy"], 2),
                }
            )

        index_by_date = {dt: idx for idx, (dt, _) in enumerate(price_history)}
        sell_events: List[Dict] = []
        for trade in trade_enriched_rows:
            if trade["action"] != "SELL":
                continue
            trade_day_idx = index_by_date.get(trade["date"])
            post_return_20d_pct = None
            post_return_60d_pct = None
            if trade_day_idx is not None:
                if trade_day_idx + 20 < len(price_history):
                    post_price_20 = price_history[trade_day_idx + 20][1]
                    post_return_20d_pct = round(((post_price_20 / trade["price"]) - 1) * 100, 4)
                if trade_day_idx + 60 < len(price_history):
                    post_price_60 = price_history[trade_day_idx + 60][1]
                    post_return_60d_pct = round(((post_price_60 / trade["price"]) - 1) * 100, 4)
            buyback_trade = next(
                (
                    buy_trade
                    for buy_trade in trade_enriched_rows
                    if buy_trade["action"] == "BUY"
                    and date.fromisoformat(buy_trade["date"]) > date.fromisoformat(trade["date"])
                ),
                None,
            )
            buyback_date = buyback_trade["date"] if buyback_trade else None
            buyback_price = buyback_trade["price"] if buyback_trade else None
            days_until_buyback = (
                (date.fromisoformat(buyback_date) - date.fromisoformat(trade["date"])).days
                if buyback_date
                else None
            )
            return_until_buyback_pct = (
                round(((buyback_price / trade["price"]) - 1) * 100, 4)
                if buyback_price is not None
                else None
            )
            sell_events.append(
                {
                    "date": trade["date"],
                    "price": trade["price"],
                    "total_score": trade["total_score"],
                    "sell_threshold": sell_threshold_safe,
                    "index_type": index_type,
                    "quantity": trade["quantity"],
                    "portfolio_cash_after_sell": round(trade["portfolio_cash_after_sell"], 2),
                    "sell_reason": [
                        condition
                        for condition, enabled in [
                            ("score_threshold", trade.get("score_threshold_today", False)),
                            ("overheat_event_active", trade.get("overheat_event_active", False)),
                            ("peakout_detected", trade.get("peakout_detected", False)),
                            ("confirmation_detected", trade.get("confirmation_detected", False)),
                            ("sell_gate_open", trade.get("sell_gate_open", False)),
                            ("cooldown_clear", trade.get("cooldown_clear", False)),
                        ]
                        if enabled
                    ],
                    "sell_reason_flags": {
                        "score_threshold": trade.get("score_threshold_today", False),
                        "overheat_event_active": trade.get("overheat_event_active", False),
                        "peakout_detected": trade.get("peakout_detected", False),
                        "confirmation_detected": trade.get("confirmation_detected", False),
                        "sell_gate_open": trade.get("sell_gate_open", False),
                        "cooldown_clear": trade.get("cooldown_clear", False),
                    },
                    "post_return_20d_pct": post_return_20d_pct,
                    "post_return_60d_pct": post_return_60d_pct,
                    "buyback_date": buyback_date,
                    "buyback_price": buyback_price,
                    "days_until_buyback": days_until_buyback,
                    "return_until_buyback_pct": return_until_buyback_pct,
                }
            )

        total_trading_days = len(price_history)
        position_state: List[int] = []
        running_shares = initial_shares
        trades_by_date: Dict[str, List[Dict]] = {}
        for trade in trades:
            trades_by_date.setdefault(trade["date"], []).append(trade)
        for dt, _ in price_history:
            day_trades = trades_by_date.get(dt, [])
            for trade in day_trades:
                if trade["action"] == "BUY":
                    running_shares += trade["quantity"]
                elif trade["action"] == "SELL":
                    running_shares = max(0, running_shares - trade["quantity"])
            position_state.append(1 if running_shares > 0 else 0)

        longest_cash_streak_days = 0
        longest_invested_streak_days = 0
        cash_streak = 0
        invested_streak = 0
        for state in position_state:
            if state == 1:
                invested_streak += 1
                cash_streak = 0
            else:
                cash_streak += 1
                invested_streak = 0
            longest_cash_streak_days = max(longest_cash_streak_days, cash_streak)
            longest_invested_streak_days = max(longest_invested_streak_days, invested_streak)

        average_score = (
            round(sum(score["score"] for score in daily_scores) / len(daily_scores), 4)
            if daily_scores
            else None
        )
        first_score = daily_scores[0]["score"] if daily_scores else None
        first_score_date = daily_scores[0]["date"] if daily_scores else None

        return {
            "final_value": round(final_value, 2),
            "buy_and_hold_final": round(buy_hold_final, 2),
            "total_return_pct": round(total_return * 100, 2),
            "cagr_pct": round(cagr * 100, 2),
            "max_drawdown_pct": max_dd,
            "trade_count": len(trades),
            "trades": trades,
            "trade_pair_diagnostics": self._build_trade_pair_diagnostics(trades, price_history),
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
                "sell_gate_block_count": sell_gate_block_count,
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
                "trade_summary": {
                    "buy_count": len(buy_trades),
                    "sell_count": len(sell_trades),
                    "trade_count": len(trades),
                    "first_trade_action": first_trade["action"] if first_trade else None,
                    "first_trade_date": first_trade["date"] if first_trade else None,
                    "first_trade_price": first_trade["price"] if first_trade else None,
                    "last_trade_action": last_trade["action"] if last_trade else None,
                    "last_trade_date": last_trade["date"] if last_trade else None,
                    "last_trade_price": last_trade["price"] if last_trade else None,
                },
                "initial_entry": {
                    "first_signal_buy_date": first_signal_buy_date_str,
                    "first_signal_buy_price": first_signal_buy_price,
                    "days_until_first_signal_buy": first_signal_buy_calendar_days,
                    "trading_days_until_first_signal_buy": first_signal_buy_trading_days,
                    "missed_return_until_first_signal_buy_pct": missed_return_until_first_signal_buy_pct,
                    "starts_invested": True,
                    "note": (
                        "strategy starts invested at start_date; initial position is not counted as a trade"
                        if first_signal_buy_trade
                        else "strategy starts invested at start_date; no BUY signal trade executed during backtest period"
                    ),
                },
                "initial_position": {
                    "starts_invested": True,
                    "initial_position_date": start_date_str,
                    "initial_position_price": start_price,
                    "initial_shares": initial_shares,
                    "initial_cash_after_buy": round(initial_cash_after_buy, 2),
                    "initial_position_is_trade": False,
                    "note": "strategy starts invested at start_date; initial position is not counted as a trade",
                },
                "sell_events": sell_events,
                "buy_events": buy_events,
                "exposure": {
                    "total_trading_days": total_trading_days,
                    "invested_days": sum(position_state),
                    "cash_days": total_trading_days - sum(position_state),
                    "invested_ratio_pct": (
                        round((sum(position_state) / total_trading_days) * 100, 4)
                        if total_trading_days > 0
                        else 0.0
                    ),
                    "cash_ratio_pct": (
                        round(((total_trading_days - sum(position_state)) / total_trading_days) * 100, 4)
                        if total_trading_days > 0
                        else 0.0
                    ),
                    "longest_cash_streak_days": longest_cash_streak_days,
                    "longest_invested_streak_days": longest_invested_streak_days,
                },
                "score_samples": {
                    "first_score_date": first_score_date,
                    "first_score": first_score,
                    "min_score": score_min,
                    "max_score": score_max,
                    "average_score": average_score,
                    "days_score_below_buy_threshold": buy_threshold_hit_days,
                    "days_score_above_sell_threshold": sell_threshold_hit_days,
                },
            },
        }
