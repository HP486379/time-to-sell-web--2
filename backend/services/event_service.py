from __future__ import annotations

import json
import logging
from datetime import UTC
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class EventService:
    def __init__(self, manual_events_path: Optional[Path] = None) -> None:
        self.manual_events_path = manual_events_path or (
            Path(__file__).resolve().parent.parent / "data" / "us_events.json"
        )
        self._diagnostics: Dict[str, object] = {
            "events_file_path": str(self.manual_events_path),
            "raw_events_count": 0,
            "parsed_events_count": 0,
            "parse_failed_count": 0,
            "parse_failed_examples": [],
            "sample_events": [],
            "today": None,
            "window_start": None,
            "window_end": None,
            "timezone": "UTC",
            "events_before_filter": 0,
            "events_after_filter": 0,
            "filtered_sample_events": [],
        }
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
        failed: List[Dict] = []
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
                failed.append(ev if isinstance(ev, dict) else {"raw": str(ev)})

        self._diagnostics.update(
            {
                "events_file_path": str(self.manual_events_path),
                "raw_events_count": len(raw),
                "parsed_events_count": len(events),
                "parse_failed_count": len(failed),
                "parse_failed_examples": failed[:3],
                "sample_events": [
                    {
                        "name": ev.get("name"),
                        "date": ev.get("date").isoformat() if isinstance(ev.get("date"), date) else str(ev.get("date")),
                        "importance": ev.get("importance"),
                    }
                    for ev in events[:3]
                ],
            }
        )
        logger.info(
            "[events-load] file=%s raw=%d parsed=%d failed=%d failed_examples=%s sample=%s",
            self.manual_events_path,
            len(raw),
            len(events),
            len(failed),
            failed[:3],
            self._diagnostics.get("sample_events"),
        )

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
        before_filter = len(self.manual_events)
        today = date.today()
        window_start = today - timedelta(days=7)
        window_end = today + timedelta(days=30)

        for ev in self.manual_events:
            ev_date = ev.get("date")
            if isinstance(ev_date, date) and window_start <= ev_date <= window_end:
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
        if window_start <= self._compute_third_wednesday(today) <= window_end:
            events.append(
                {
                    "name": "FOMC",
                    "date": self._compute_third_wednesday(today),
                    "importance": 3,
                    "source": "computed",
                    "description": "Computed third Wednesday event",
                }
            )

        # 雇用統計（第1金曜の簡易近似）
        if window_start <= self._first_friday(today) <= window_end:
            events.append(
                {
                    "name": "US Jobs Report",
                    "date": self._first_friday(today),
                    "importance": 3,
                    "source": "computed",
                    "description": "Computed first Friday event",
                }
            )

        self._diagnostics.update(
            {
                "today": target.isoformat(),
                "request_target": target.isoformat(),
                "today_runtime": today.isoformat(),
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
                "timezone": str(UTC),
                "events_before_filter": before_filter,
                "events_after_filter": len(events),
                "filtered_sample_events": [
                    {
                        "name": ev.get("name"),
                        "date": ev.get("date").isoformat() if isinstance(ev.get("date"), date) else str(ev.get("date")),
                        "importance": ev.get("importance"),
                    }
                    for ev in events[:3]
                ],
            }
        )
        logger.info(
            "[events-filter] request_target=%s runtime_today=%s window=(%s..%s) tz=%s before=%d after=%d sample=%s",
            target,
            today,
            window_start,
            window_end,
            UTC,
            before_filter,
            len(events),
            self._diagnostics.get("filtered_sample_events"),
        )
        return events

    def get_diagnostics(self) -> Dict[str, object]:
        return dict(self._diagnostics)
