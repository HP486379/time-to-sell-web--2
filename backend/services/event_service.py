from __future__ import annotations

import json
import logging
from datetime import date, timedelta
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
        except Exception:
            logger.exception("Failed to read manual events JSON: %s", self.manual_events_path)
            return []

        if not isinstance(raw, list):
            logger.warning("Manual events JSON is not a list: %s", self.manual_events_path)
            return []

        events: List[Dict] = []
        for ev in raw:
            try:
                if not isinstance(ev, dict):
                    raise TypeError("event entry is not an object")

                event_date = date.fromisoformat(ev["date"])
                events.append(
                    {
                        "name": ev["name"],
                        "date": event_date,
                        "importance": int(ev["importance"]),
                        "source": ev.get("source"),
                        "description": ev.get("description"),
                    }
                )
            except (KeyError, ValueError, TypeError):
                logger.warning("Invalid manual event entry skipped: %s", ev)

        return events

    def _compute_third_wednesday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        offset = (2 - weekday) % 7  # Wednesday = 2
        return first_day + timedelta(days=offset + 14)

    def _first_friday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        offset = (4 - weekday) % 7  # Friday = 4
        return first_day + timedelta(days=offset)

    def get_events_for_date(self, target: date) -> List[Dict]:
        """
        指定日のイベント一覧を返す。
        現時点では manual_events.json の日付一致分に加え、
        月次の代表イベントを簡易的に補完する。
        """
        events: List[Dict] = []

        for ev in self.manual_events:
            ev_date = ev.get("date")
            if ev_date == target:
                events.append(
                    {
                        "name": ev.get("name"),
                        "date": ev_date,
                        "importance": int(ev.get("importance", 1)),
                        "source": ev.get("source"),
                        "description": ev.get("description"),
                    }
                )

        # FOMC（第3水曜の簡易近似）
        if target == self._compute_third_wednesday(target):
            events.append(
                {
                    "name": "FOMC",
                    "date": target,
                    "importance": 3,
                    "source": "computed",
                    "description": "Computed third Wednesday event",
                }
            )

        # 雇用統計（第1金曜の簡易近似）
        if target == self._first_friday(target):
            events.append(
                {
                    "name": "US Jobs Report",
                    "date": target,
                    "importance": 3,
                    "source": "computed",
                    "description": "Computed first Friday event",
                }
            )

        return events
