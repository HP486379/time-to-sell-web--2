from typing import List, Optional, Tuple, Dict, Any

ULTRA_LONG_ATTENUATION_FLOOR = 0.6
ULTRA_LONG_ATTENUATION_SLOPE = 1.5

# NEW: convergence adjustment amplitude (max +/- points added to technical_score)
CONVERGENCE_ADJ_MAX = 8.0


def moving_average(prices: List[float], window: int) -> List[float]:
    if len(prices) < window:
        raise ValueError(f"Not enough data for MA{window}")
    ma_values = []
    for i in range(window - 1, len(prices)):
        window_prices = prices[i - window + 1 : i + 1]
        ma_values.append(sum(window_prices) / window)
    return ma_values


def latest_moving_average(prices: List[float], window: int) -> Optional[float]:
    if len(prices) < window:
        return None
    return sum(prices[-window:]) / window


def calculate_ultra_long_mas(price_history: List[Tuple[str, float]]) -> Tuple[Optional[float], Optional[float]]:
    closes = [p[1] for p in price_history]
    ma500 = latest_moving_average(closes, 500)
    ma1000 = latest_moving_average(closes, 1000)
    return ma500, ma1000


def below_ratio(price: float, ma: Optional[float]) -> Optional[float]:
    if ma is None or ma == 0:
        return None
    if price >= ma:
        return 0.0
    return (ma - price) / ma


def calculate_ultra_long_attenuation(
    price: float,
    ma500: Optional[float],
    ma1000: Optional[float],
) -> Optional[float]:
    dd500 = below_ratio(price, ma500)
    dd1000 = below_ratio(price, ma1000)
    if dd500 is None or dd1000 is None:
        return None
    ultra_dd = max(dd500, dd1000)
    attenuation = 1.0 - ultra_dd * ULTRA_LONG_ATTENUATION_SLOPE
    return max(ULTRA_LONG_ATTENUATION_FLOOR, attenuation)


def clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


# =========================
# Convergence detection (NEW)
# =========================

def _slope(series: List[float], lookback: int = 5) -> Optional[float]:
    """(last - value N bars ago) / N"""
    if series is None or len(series) < lookback + 1:
        return None
    return (series[-1] - series[-(lookback + 1)]) / lookback


def detect_ma200_convergence(
    closes: List[float],
    deviation_trigger: float = 0.15,  # 15%: 収斂判定を本気で見る入口
    danger_full: float = 0.25,        # 25%: danger=100相当
    slope_lookback: int = 5,
) -> Dict[str, Any]:
    """
    インデックス向け「200日線への収斂開始」を判定して返す。
    戻り値は debug 向け dict（既存APIは壊さない）。
    """
    if len(closes) < 200:
        return {
            "side": "neutral",
            "score": 0.0,
            "speed": "unknown",
            "danger": 0.0,
            "deviation_200": None,
            "signals": {"not_enough_data": True},
        }

    price = closes[-1]

    ma10_series = moving_average(closes, 10)
    ma25_series = moving_average(closes, 25)
    ma50_series = moving_average(closes, 50)
    ma200_series = moving_average(closes, 200)

    ma10 = ma10_series[-1]
    ma25 = ma25_series[-1]
    ma50 = ma50_series[-1]
    ma200 = ma200_series[-1]

    deviation_200 = (price - ma200) / ma200  # +: 上乖離, -: 下乖離

    danger = min(abs(deviation_200) / danger_full, 1.0) * 100.0

    upper_extreme = deviation_200 >= deviation_trigger
    lower_extreme = deviation_200 <= -deviation_trigger

    if not (upper_extreme or lower_extreme):
        return {
            "side": "neutral",
            "score": 0.0,
            "speed": "unknown",
            "danger": round(danger, 2),
            "deviation_200": round(deviation_200 * 100, 2),  # %
            "ma10": round(ma10, 2),
            "ma25": round(ma25, 2),
            "ma50": round(ma50, 2),
            "ma200": round(ma200, 2),
            "signals": {"deviation_small": True},
        }

    ma10_slope = _slope(ma10_series, lookback=slope_lookback)
    ma25_slope = _slope(ma25_series, lookback=slope_lookback)

    signals: Dict[str, bool] = {}
    score = 0.0

    def add(cond: bool, pts: float, name: str) -> None:
        nonlocal score
        signals[name] = bool(cond)
        if cond:
            score += pts

    if upper_extreme:
        side = "down_convergence"
        add(ma10 < ma25, 30, "ma10_below_ma25")
        add(ma25 <= ma50, 25, "ma25_below_or_eq_ma50")
        add((ma10_slope is not None) and (ma10_slope < 0), 20, "ma10_slope_down")
        add((ma25_slope is not None) and (ma25_slope <= 0), 10, "ma25_slope_non_up")
        add(price < ma10, 15, "price_below_ma10")

        stack_complete = (ma10 < ma25 < ma50)
        stack_partial = (ma10 < ma25) and not (ma25 <= ma50)
        strong = (ma10_slope is not None) and (ma10_slope < 0)
    else:
        side = "up_convergence"
        add(ma10 > ma25, 30, "ma10_above_ma25")
        add(ma25 >= ma50, 25, "ma25_above_or_eq_ma50")
        add((ma10_slope is not None) and (ma10_slope > 0), 20, "ma10_slope_up")
        add((ma25_slope is not None) and (ma25_slope >= 0), 10, "ma25_slope_non_down")
        add(price > ma10, 15, "price_above_ma10")

        stack_complete = (ma10 > ma25 > ma50)
        stack_partial = (ma10 > ma25) and not (ma25 >= ma50)
        strong = (ma10_slope is not None) and (ma10_slope > 0)

    score = max(0.0, min(score, 100.0))

    if stack_complete and strong:
        speed = "fast"
    elif stack_partial and strong:
        speed = "normal"
    elif strong:
        speed = "slow"
    else:
        speed = "unknown"

    return {
        "side": side,
        "score": round(score, 2),
        "speed": speed,
        "danger": round(danger, 2),
        "deviation_200": round(deviation_200 * 100, 2),  # %
        "ma10": round(ma10, 2),
        "ma25": round(ma25, 2),
        "ma50": round(ma50, 2),
        "ma200": round(ma200, 2),
        "signals": signals,
        "debug": {
            "upper_extreme": upper_extreme,
            "lower_extreme": lower_extreme,
            "ma10_slope": None if ma10_slope is None else round(ma10_slope, 6),
            "ma25_slope": None if ma25_slope is None else round(ma25_slope, 6),
            "deviation_trigger": deviation_trigger,
            "danger_full": danger_full,
            "slope_lookback": slope_lookback,
        },
    }


def _calc_convergence_adjustment(convergence: Dict[str, Any], amp: float = CONVERGENCE_ADJ_MAX) -> float:
    """
    Convergence is a timing signal, so keep it small (max +/- amp points).
    - down_convergence (overheated -> decelerating): + (more "sell-ish")
    - up_convergence (panic -> rebound): - (less "sell-ish")
    Multiply convergence score by danger so it only matters in extremes.
    """
    if not convergence:
        return 0.0

    side = convergence.get("side")
    c_score = convergence.get("score", 0.0) or 0.0     # 0-100
    danger = convergence.get("danger", 0.0) or 0.0     # 0-100

    raw = (float(c_score) / 100.0) * (float(danger) / 100.0)  # 0-1

    if side == "down_convergence":
        return +amp * raw
    if side == "up_convergence":
        return -amp * raw
    return 0.0


def _build_multi_ma_status(price: float, closes: List[float]) -> Dict[str, Any]:
    if len(closes) < 200:
        return {
            "dev10": None,
            "dev50": None,
            "dev200": None,
            "level": 0,
            "label": "",
            "text": "",
        }

    ma10 = moving_average(closes, 10)[-1]
    ma50 = moving_average(closes, 50)[-1]
    ma200 = moving_average(closes, 200)[-1]

    dev10 = price / ma10 - 1
    dev50 = price / ma50 - 1
    dev200 = price / ma200 - 1

    th10 = 0.03
    th50 = 0.05
    th200 = 0.08

    level = 0
    label = ""
    text = ""

    if dev200 >= th200:
        level = 1
        label = "出口注意：長期が過熱"
        text = "長期の乖離が大きく、出口を意識し始める水準です。"

    if dev200 >= th200 and dev50 >= th50:
        level = 2
        label = "天井圏・調整兆し"
        text = "中期も過熱。調整（下落/横ばい）が出やすい状態です。"

    if dev200 >= th200 and dev50 >= th50 and dev10 >= th10:
        level = 3
        label = "過熱圏：利確優位"
        text = "短期も過熱。利確が優位になりやすい出口圏です。"

    return {
        "dev10": round(dev10, 4),
        "dev50": round(dev50, 4),
        "dev200": round(dev200, 4),
        "level": level,
        "label": label,
        "text": text,
    }


def calculate_technical_score(price_history: List[Tuple[str, float]], base_window: int = 200):
    closes = [p[1] for p in price_history]

    # --- Existing score logic (kept) ---
    windows = sorted(set([20, 60, 200, base_window]))
    ma_series = {window: moving_average(closes, window) for window in windows}

    def latest_ma(window: int) -> float:
        return ma_series[window][-1]

    ma_base = latest_ma(base_window)
    current_price = closes[-1]

    short_window, mid_window, long_window = windows[0], windows[1], windows[-1]
    ma_short_series = ma_series[short_window]
    ma_mid_series = ma_series[mid_window]
    ma_long_series = ma_series[long_window]
    ma_short = ma_short_series[-1]
    ma_mid = ma_mid_series[-1]
    ma_long = ma_long_series[-1]

    d = (current_price - ma_base) / ma_base * 100

    # base score
    if d <= -20:
        t_base = 0
    elif -20 < d < 0:
        t_base = 30 * (d + 20) / 20
    elif 0 <= d < 10:
        t_base = 30 + 20 * d / 10
    elif 10 <= d < 25:
        t_base = 50 + 30 * (d - 10) / 15
    else:
        t_base = 100

    # trend evaluation
    def is_increasing(series: List[float]) -> bool:
        if len(series) < 20:
            return False
        return series[-1] > series[-20]

    def is_decreasing(series: List[float]) -> bool:
        if len(series) < 20:
            return False
        return series[-1] < series[-20]

    if ma_short > ma_mid > ma_long and is_increasing(ma_short_series[-20:]):
        t_trend = 10
    elif ma_short < ma_mid < ma_long and is_decreasing(ma_short_series[-20:]):
        t_trend = -10
    else:
        t_trend = 0

    technical_score_raw = clip(t_base + t_trend)

    # --- NEW: convergence detection + small adjustment ---
    convergence = detect_ma200_convergence(closes)
    t_conv_adj = _calc_convergence_adjustment(convergence, amp=CONVERGENCE_ADJ_MAX)

    technical_score = clip(technical_score_raw + t_conv_adj)

    multi_ma = _build_multi_ma_status(current_price, closes)

    return round(technical_score, 2), {
        "d": round(d, 2),
        "T_base": round(t_base, 2),
        "T_trend": round(t_trend, 2),
        "T_conv_adj": round(t_conv_adj, 2),
        "technical_score_raw": round(technical_score_raw, 2),
        "technical_score_adj": round(technical_score, 2),
        "base_window": base_window,
        "ma_base": round(ma_base, 2),
        "convergence": convergence,
        "convergence_adj_max": CONVERGENCE_ADJ_MAX,
        "multi_ma": multi_ma,
    }
