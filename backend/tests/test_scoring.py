from datetime import date, timedelta
import os
import sys

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from scoring.technical import calculate_technical_score
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
        (4000, 4000, 30),
        (4000, 4400, 50),
        (4000, 5000, 80),
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
    assert round(e_adj, 2) == round(-10 * (5 / 7), 2)


def test_label_boundaries():
    assert get_label(85) == "一部利確を強く検討"
    assert get_label(65) == "利確を検討"
    assert get_label(50) == "ホールド"
    assert get_label(20) == "買い増し・追加投資検討"
