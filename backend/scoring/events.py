from datetime import date
from typing import Dict, List, Tuple


def calculate_event_adjustment(today: date, events: List[Dict]) -> Tuple[float, Dict]:
    risks = []
    for event in events:
        days_diff = (event["date"] - today).days
        importance = event.get("importance", 1)

        if importance == 5:
            w_imp = 1.0
        elif importance == 4:
            w_imp = 0.7
        elif importance == 3:
            w_imp = 0.4
        else:
            w_imp = 0.2

        if abs(days_diff) > 7:
            f_prox = 0.0
        else:
            f_prox = 1 - abs(days_diff) / 7.0

        r_i = w_imp * f_prox
        risks.append({
            "risk": r_i,
            "event": event,
        })

    if not risks:
        return 0.0, {"E_adj": 0.0, "R_max": 0.0, "effective_event": None}

    max_risk_entry = max(risks, key=lambda x: x["risk"])
    r_max = max_risk_entry["risk"]
    e_adj = -10 * r_max

    return round(e_adj, 2), {
        "E_adj": round(e_adj, 2),
        "R_max": round(r_max, 3),
        "effective_event": max_risk_entry["event"],
    }
