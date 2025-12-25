from datetime import date, timedelta
from typing import Dict, List


class EventService:
    def _compute_third_wednesday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        # Wednesday is 2
        offset = (2 - weekday) % 7
        third_wed = first_day + timedelta(days=offset + 14)
        return third_wed

    def _first_friday(self, target: date) -> date:
        first_day = target.replace(day=1)
        weekday = first_day.weekday()
        offset = (4 - weekday) % 7  # Friday is 4
        return first_day + timedelta(days=offset)

    def _cpi_release_day(self, target: date) -> date:
        # Approximate: 10日をデフォルトとする（実運用ではAPI差し替え）
        day = 10
        return target.replace(day=day)

    def _monthly_events(self, today: date) -> List[Dict]:
        month_ref = today.replace(day=1)
        next_month = (month_ref.replace(day=28) + timedelta(days=4)).replace(day=1)
        candidates = [month_ref, next_month]
        events: List[Dict] = []
        for month in candidates:
            events.extend(
                [
                    {"name": "FOMC", "importance": 5, "date": self._compute_third_wednesday(month)},
                    {"name": "CPI Release", "importance": 4, "date": self._cpi_release_day(month)},
                    {"name": "Nonfarm Payrolls", "importance": 3, "date": self._first_friday(month)},
                ]
            )
        return events

    def get_events_for_date(self, target: date) -> List[Dict]:
        window_days = 30
        events = self._monthly_events(target)
        windowed = [
            event
            for event in events
            if -7 <= (event["date"] - target).days <= window_days
        ]
        return sorted(windowed, key=lambda e: e["date"])

    def get_events(self) -> List[Dict]:
        return self.get_events_for_date(date.today())
