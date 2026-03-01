from datetime import date

from backend.services.event_service import EventService


def test_manual_events_loaded_on_init():
    service = EventService()
    assert len(service.manual_events) > 0


def test_get_events_for_date_filters_window_and_includes_ism_march_2():
    service = EventService()

    events = service.get_events_for_date(date(2026, 3, 2))

    assert any(e["name"] == "ISM Manufacturing" and e["date"] == "2026-03-02" for e in events)
    assert all(isinstance(e["date"], str) for e in events)

    lower = date(2026, 2, 23)
    upper = date(2026, 4, 1)
    for e in events:
        d = date.fromisoformat(e["date"])
        assert lower <= d <= upper
