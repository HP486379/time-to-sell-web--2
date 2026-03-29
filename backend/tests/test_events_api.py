import os
import sys
from datetime import date

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main


def test_events_api_accepts_date_query_param(monkeypatch):
    captured = {}

    def fake_get_events_for_date(target: date):
        captured["target"] = target
        return [{"date": target.isoformat(), "name": "dummy"}]

    monkeypatch.setattr(main.event_service, "get_events_for_date", fake_get_events_for_date)

    body = main.get_events_api(date="2026-03-20")

    assert captured["target"].isoformat() == "2026-03-20"
    assert body["target"] == "2026-03-20"
    assert body["events"] == [{"date": "2026-03-20", "name": "dummy"}]
    assert isinstance(body["manual_count"], int)


def test_events_api_prefers_date_over_date_str(monkeypatch):
    captured = {}

    def fake_get_events_for_date(target: date):
        captured["target"] = target
        return []

    monkeypatch.setattr(main.event_service, "get_events_for_date", fake_get_events_for_date)

    body = main.get_events_api(date="2026-03-20", date_str="2026-03-21")

    assert captured["target"].isoformat() == "2026-03-20"
    assert body["target"] == "2026-03-20"
    assert isinstance(body["manual_count"], int)


def test_events_api_accepts_date_str_query_param(monkeypatch):
    captured = {}

    def fake_get_events_for_date(target: date):
        captured["target"] = target
        return []

    monkeypatch.setattr(main.event_service, "get_events_for_date", fake_get_events_for_date)

    body = main.get_events_api(date_str="2026-03-20")

    assert captured["target"].isoformat() == "2026-03-20"
    assert body["target"] == "2026-03-20"
    assert isinstance(body["manual_count"], int)
