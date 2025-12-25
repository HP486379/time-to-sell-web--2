from typing import List, Tuple


def moving_average(prices: List[float], window: int) -> List[float]:
    if len(prices) < window:
        raise ValueError(f"Not enough data for MA{window}")
    ma_values = []
    for i in range(window - 1, len(prices)):
        window_prices = prices[i - window + 1 : i + 1]
        ma_values.append(sum(window_prices) / window)
    return ma_values


def clip(value: float, lower: float = 0.0, upper: float = 100.0) -> float:
    return max(lower, min(upper, value))


def calculate_technical_score(price_history: List[Tuple[str, float]], base_window: int = 200):
    closes = [p[1] for p in price_history]

    # Calculate every MA we rely on so we never reference an undefined variable
    windows = sorted(set([20, 60, 200, base_window]))
    ma_series = {window: moving_average(closes, window) for window in windows}

    def latest_ma(window: int) -> float:
        return ma_series[window][-1]

    ma_base = latest_ma(base_window)
    current_price = closes[-1]

    # Align the trend check with the ordered MA set (short/mid/long)
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

    technical_score = clip(t_base + t_trend)

    return round(technical_score, 2), {
        "d": round(d, 2),
        "T_base": round(t_base, 2),
        "T_trend": round(t_trend, 2),
        "base_window": base_window,
        "ma_base": round(ma_base, 2),
    }
