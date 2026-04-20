from datetime import date, timedelta
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scoring.technical import calculate_technical_score, calculate_ultra_long_attenuation_details
from scoring.macro import calculate_macro_score
from scoring.events import calculate_event_adjustment
from scoring.total_score import get_label


def build_history(ma200_value: float, current_price: float):
    history = []
    # create 199 entries at ma200_value then final current
    base_date = date(2024, 1, 1)
    for i in range(199):
        history.append(((base_date + timedelta(days=i)).isoformat(), ma200_value))
    history.append(((base_date + timedelta(days=199)).isoformat(), current_price))
    return history


def test_technical_score_cases():
    cases = [
        (4000, 4000, 40),
        (4000, 4400, 70),
        (4000, 5000, 95),
        (4000, 3000, 0),
    ]
    for ma, price, expected in cases:
        score, details = calculate_technical_score(build_history(ma, price))
        assert round(details["T_base"]) == expected


def test_macro_score_example():
    r_history = [1] * 8 + [5] * 2
    cpi_history = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    vix_history = [10, 20, 30, 40, 50]

    macro_score, details = calculate_macro_score(
        (r_history, 5), (cpi_history, 6), (vix_history, 20)
    )
    assert round(macro_score) == 53
    assert round(details["p_r"], 1) == 0.8


def test_event_adjustment_example():
    today = date(2025, 3, 1)
    events = [
        {"name": "FOMC", "importance": 5, "date": date(2025, 3, 3)},
    ]
    e_adj, details = calculate_event_adjustment(today, events)
    assert round(details["R_max"], 3) == round(5 / 7, 3)
    assert -10.0 < e_adj < 0.0


def test_label_boundaries():
    assert get_label(85) == "一部利確を強く検討"
    assert get_label(65) == "利確を検討"
    assert get_label(50) == "ホールド"
    assert get_label(20) == "買い増し・追加投資検討"


def test_ultra_long_attenuation_no_upside_penalty_in_normal_uptrend():
    attenuation, debug = calculate_ultra_long_attenuation_details(
        price=115.0,
        ma500=100.0,
        ma1000=100.0,
    )
    assert attenuation == 1.0
    assert debug["up_deviation_500"] == 0.15
    assert debug["upside_attenuation"] == 1.0


def test_ultra_long_attenuation_adds_mild_upside_guard():
    attenuation, debug = calculate_ultra_long_attenuation_details(
        price=130.0,
        ma500=100.0,
        ma1000=105.0,
    )
    assert attenuation is not None
    assert 0.99 <= attenuation <= 1.0
    assert debug["final_attenuation"] == round(attenuation, 6)
    assert debug["up_deviation_500"] == 0.3
