import logging
import os
from typing import Optional

from .technical import calculate_ultra_long_attenuation_details, clip

logger = logging.getLogger(__name__)


def _debug_enabled() -> bool:
    return os.getenv("ATTENUATION_DEBUG_LOG", "0").lower() in {"1", "true", "yes", "on"}


def calculate_total_score(
    technical: float,
    macro: float,
    event_adjustment: float,
    current_price: Optional[float] = None,
    ma500: Optional[float] = None,
    ma1000: Optional[float] = None,
    ma50: Optional[float] = None,
    ma200: Optional[float] = None,
    ma50_slope: Optional[float] = None,
    ma200_slope: Optional[float] = None,
) -> float:
    raw_score = round(0.7 * technical + 0.3 * macro + event_adjustment, 2)
    attenuation = None
    attenuation_debug = None
    if current_price is not None:
        attenuation, attenuation_debug = calculate_ultra_long_attenuation_details(
            current_price,
            ma500,
            ma1000,
            ma50=ma50,
            ma200=ma200,
            ma50_slope=ma50_slope,
            ma200_slope=ma200_slope,
        )

    # 最終段で連続減衰を適用（超長期ガード）
    final_score = raw_score * attenuation if attenuation is not None else raw_score

    if _debug_enabled():
        logger.info(
            "[attenuation-debug] technical=%.4f macro=%.4f event_adj=%.4f raw_score=%.4f "
            "downside_attenuation=%s upside_attenuation=%s final_attenuation=%s "
            "ma50_slope=%s ma200_slope=%s strong_trend=%s final_score=%.4f",
            technical,
            macro,
            event_adjustment,
            raw_score,
            None if attenuation_debug is None else attenuation_debug.get("downside_attenuation"),
            None if attenuation_debug is None else attenuation_debug.get("upside_attenuation"),
            None if attenuation_debug is None else attenuation_debug.get("final_attenuation"),
            None if attenuation_debug is None else attenuation_debug.get("ma50_slope"),
            None if attenuation_debug is None else attenuation_debug.get("ma200_slope"),
            None if attenuation_debug is None else attenuation_debug.get("strong_trend"),
            final_score,
        )

    return clip(final_score)


def get_label(score: float) -> str:
    if score >= 80:
        return "一部利確を強く検討"
    if score >= 60:
        return "利確を検討"
    if score >= 40:
        return "ホールド"
    return "買い増し・追加投資検討"
