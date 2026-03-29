from typing import Optional

from .technical import calculate_ultra_long_attenuation, clip


def calculate_total_score(
    technical: float,
    macro: float,
    event_adjustment: float,
    current_price: Optional[float] = None,
    ma500: Optional[float] = None,
    ma1000: Optional[float] = None,
) -> float:
    raw_score = round(0.7 * technical + 0.3 * macro + event_adjustment, 2)
    attenuation = (
        calculate_ultra_long_attenuation(current_price, ma500, ma1000)
        if current_price is not None
        else None
    )
    # 最終段で連続減衰を適用（超長期ガード）
    final_score = raw_score * attenuation if attenuation is not None else raw_score
    return clip(final_score)


def get_label(score: float) -> str:
    if score >= 80:
        return "一部利確を強く検討"
    if score >= 60:
        return "利確を検討"
    if score >= 40:
        return "ホールド"
    return "買い増し・追加投資検討"
