from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
import json
import logging
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self, manual_events_path: Optional[Path] = None) -> None:
        self.manual_events_path = manual_events_path or (
            Path(__file__).resolve().parent.parent / "data" / "us_events.json"
        )
        self.manual_events: List[Dict] = self._load_manual_events()

    def _load_manual_events(self) -> List[Dict]:
        if not self.manual_events_path.exists():
            logger.warning("Manual events file not found: %s", self.manual_events_path)
            return []
        try:
            raw = json.loads(self.manual_events_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.exception("Failed to parse manual events JSON: %s", self.manual_events_path)
            return []

                events: List[Dict] = []
        for ev in raw:
            try:
                event_date = date.fromisoformat(ev["date"])
                events.append(
                    {
                        "name": ev["name"],
                        "date": event_date,
                        "importance": int(ev["importance"]),
                    }
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("Invalid manual event entry skipped: %s", ev)

        return events

    def _compute_third_wednesday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        offset = (2 - weekday) % 7
        return first_day + timedelta(days=offset + 14)

    def _first_friday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        offset = (4 - weekday) % 7
        return first_day + timedelta(days=offset)

    def _cpi_release_day(self, target: date) -> date:
        return target.replace(day=10)

    def _monthly_events_fallback(self, today: date) -> List[Dict]:
        month_ref = today.replace(day=1)
        next_month = (month_ref.replace(day=28) + timedelta(days=4)).replace(day=1)
        candidates = [month_ref, next_month]
        events: List[EventItem] = []

        for month in candidates:
            events.extend(
                [
                    {"name": "FOMC", "importance": 5, "date": self._compute_third_wednesday(month)},
                    {"name": "CPI", "importance": 4, "date": self._cpi_release_day(month)},
                    {"name": "Nonfarm Payrolls", "importance": 3, "date": self._first_friday(month)},
                ]
            )
        return events

    # ===== パブリック API =====

    def _filter_window(self, events: List[Dict], target: date) -> List[Dict]:
        """target の前後 [-7, +30] 日に入るイベントだけに絞る."""
        window_days = 30
        windowed = [
            event
            for event in self.manual_events
            if -7 <= (event["date"] - target).days <= window_days
        ]
        if not windowed:
            windowed = [
                event
                for event in self._monthly_events_fallback(target)
                if -7 <= (event["date"] - target).days <= window_days
            ]
        return sorted(windowed, key=lambda e: e["date"])

    def get_events(self) -> List[Dict]:
        """今日を基準にイベントを取得（既存 API 互換用）"""
        return self.get_events_for_date(date.today())
