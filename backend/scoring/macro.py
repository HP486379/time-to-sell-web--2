from typing import Dict, List, Tuple


def percentile_rank(series: List[float], current: float) -> float:
    sorted_series = sorted(series)
    count = sum(1 for x in sorted_series if x < current)
    return count / len(sorted_series)


def calculate_macro_score(
    r_10y: Tuple[List[float], float], cpi: Tuple[List[float], float], vix: Tuple[List[float], float]
) -> Tuple[float, Dict]:
    r_history, r_current = r_10y
    cpi_history, cpi_current = cpi
    vix_history, vix_current = vix

    p_r = percentile_rank(r_history, r_current)
    p_cpi = percentile_rank(cpi_history, cpi_current)
    p_vix = percentile_rank(vix_history, vix_current)

    m_score = 100 * (0.4 * p_r + 0.3 * p_cpi + 0.3 * p_vix)

    return round(m_score, 2), {
        "p_r": round(p_r, 3),
        "p_cpi": round(p_cpi, 3),
        "p_vix": round(p_vix, 3),
        "M": round(m_score, 2),
    }
