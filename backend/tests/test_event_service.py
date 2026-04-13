import json
from datetime import date, timedelta
from pathlib import Path

from backend.services.event_service import EventService


def test_get_events_for_date_uses_range_window(tmp_path: Path):
    today = date.today()
    payload = [
        {"name": "CPI", "date": (today - timedelta(days=1)).isoformat(), "importance": 4},
        {"name": "NFP", "date": (today + timedelta(days=5)).isoformat(), "importance": 5},
        {"name": "Old", "date": (today - timedelta(days=40)).isoformat(), "importance": 3},
    ]
    path = tmp_path / "events.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    service = EventService(manual_events_path=path)
    events = service.get_events_for_date(today)
    names = {ev["name"] for ev in events}

    assert "CPI" in names
    assert "NFP" in names
    assert "Old" not in names

    diag = service.get_diagnostics()
    assert diag["events_before_filter"] == 3
    assert diag["events_after_filter"] >= 2
    assert diag["window_start"] == (today - timedelta(days=7)).isoformat()
    assert diag["window_end"] == (today + timedelta(days=30)).isoformat()
