from datetime import date
from typing import Dict, List, Optional, Tuple


def _normalize_event_date(raw_date) -> Optional[date]:
    if isinstance(raw_date, date):
        return raw_date
    if isinstance(raw_date, str):
        try:
            return date.fromisoformat(raw_date)
        except Exception:
            return None
    return None


def calculate_event_adjustment(today: date, events: List[Dict]) -> Tuple[float, Dict]:
    risks = []
    normalized_events: List[Dict] = []

    for event in events:
        event_date = _normalize_event_date(event.get("date"))
        if event_date is None:
            continue

        normalized_event = {**event, "date": event_date}
        normalized_events.append(normalized_event)

        days_diff = (event_date - today).days
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
            "event": normalized_event,
        })

    if not risks:
        return 0.0, {"E_adj": 0.0, "R_max": 0.0, "effective_event": None, "events": normalized_events}

    max_risk_entry = max(risks, key=lambda x: x["risk"])
    r_max = max_risk_entry["risk"]
    e_adj = -10 * r_max

    return round(e_adj, 2), {
        "E_adj": round(e_adj, 2),
        "R_max": round(r_max, 3),
        "effective_event": max_risk_entry["event"],
        "events": normalized_events,
    }
