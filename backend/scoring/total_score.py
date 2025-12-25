from .technical import clip


def calculate_total_score(technical: float, macro: float, event_adjustment: float) -> float:
    score = 0.7 * technical + 0.3 * macro + event_adjustment
    return clip(round(score, 2))


def get_label(score: float) -> str:
    if score >= 80:
        return "一部利確を強く検討"
    if score >= 60:
        return "利確を検討"
    if score >= 40:
        return "ホールド"
    return "買い増し・追加投資検討"
