from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional
import json
import logging

logger = logging.getLogger(__name__)


@dataclass
class EventItem:
    name: str
    importance: int
    date: date
    source: str  # "manual" or "heuristic"
    description: Optional[str] = None


class EventService:
    """
    経済イベントを管理するサービス。

    - 手動 JSON (backend/data/us_events.json) のみを使用
    """

    def __init__(self) -> None:
        self.manual_events: List[EventItem] = self._load_manual_events()
        logger.info("[EventService] loaded %d manual events", len(self.manual_events))

    # =============== manual JSON 読み込み ===============

    def _normalize_event_date(self, raw_date) -> Optional[date]:
        if isinstance(raw_date, date):
            return raw_date
        if isinstance(raw_date, str):
            try:
                return date.fromisoformat(raw_date)
            except Exception:
                return None
        return None

    def _load_manual_events(self) -> List[EventItem]:
        """
        backend/data/us_events.json からイベントを読み込む。

        期待フォーマット（実際のファイルと一致）:
        [
          { "date": "2025-01-29", "name": "FOMC",    "importance": 5 },
          { "date": "2025-02-14", "name": "CPI (US)", "importance": 4 },
          ...
        ]
        """
        events: List[EventItem] = []
        data_path = Path(__file__).resolve().parent.parent / "data" / "us_events.json"

        if not data_path.exists():
            logger.warning("[EventService] manual events file not found: %s", data_path)
            return events

        try:
            with data_path.open("r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as exc:
            logger.error("[EventService] failed to load manual events json: %s", exc)
            return events

        # 配列 or { "events": [...] } or { "manual_events": [...] } を許容
        if isinstance(raw, list):
            raw_events = raw
        elif isinstance(raw, dict) and isinstance(raw.get("events"), list):
            raw_events = raw["events"]
        elif isinstance(raw, dict) and isinstance(raw.get("manual_events"), list):
            raw_events = raw["manual_events"]
        else:
            logger.error("[EventService] invalid manual events format in %s", data_path)
            return events

        for item in raw_events:
            try:
                event_date = self._normalize_event_date(item.get("date"))
                if event_date is None:
                    raise ValueError("invalid date")

                name = str(item.get("name", "")).strip()
                importance = int(item.get("importance", 3))
                description = item.get("description")

                events.append(
                    EventItem(
                        name=name or "Unknown",
                        importance=importance,
                        date=event_date,
                        source="manual",
                        description=description if description else None,
                    )
                )
            except Exception as exc:  # フォーマットがおかしい行はスキップ
                logger.warning("[EventService] skip invalid manual event %s (%s)", item, exc)

        # 日付順にしておく
        events.sort(key=lambda e: e.date)
        return events

    # =============== 簡易ヒューリスティックイベント ===============

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
        # Approximate: 10日をデフォルトとする（実運用ではAPI差し替え予定だったが、今は使用しない）
        day = 10
        return target.replace(day=day)

    def _monthly_events(self, today: date) -> List[EventItem]:
        """
        ヒューリスティックで「今月 & 来月」の代表イベントをざっくり生成。
        """
        month_ref = today.replace(day=1)
        next_month = (month_ref.replace(day=28) + timedelta(days=4)).replace(day=1)
        candidates = [month_ref, next_month]
        events: List[EventItem] = []

        for month in candidates:
            events.extend(
                [
                    EventItem(
                        name="FOMC",
                        importance=5,
                        date=self._compute_third_wednesday(month),
                        source="heuristic",
                        description=None,
                    ),
                    EventItem(
                        name="CPI Release",
                        importance=4,
                        date=self._cpi_release_day(month),
                        source="heuristic",
                        description=None,
                    ),
                    EventItem(
                        name="Nonfarm Payrolls",
                        importance=3,
                        date=self._first_friday(month),
                        source="heuristic",
                        description=None,
                    ),
                ]
            )
        return events

    # =============== 公開 API ===============

    def get_events_for_date(self, target: date) -> List[Dict]:
        """
        外部公開用。辞書形式のリストで返す。

        返却対象は target-7日〜target+30日に含まれるイベントのみ。
        """
        start = target - timedelta(days=7)
        end = target + timedelta(days=30)

        windowed = [e for e in self.manual_events if start <= e.date <= end]
        windowed.sort(key=lambda e: e.date)

        events: List[Dict] = []
        for it in windowed:
            event_date = self._normalize_event_date(it.date)
            if event_date is None:
                logger.warning("[EventService] invalid date format in runtime: %s", it.date)
                continue

            events.append(
                {
                    "name": it.name,
                    "importance": it.importance,
                    "date": event_date.isoformat(),
                    "source": it.source,
                    "description": it.description,
                }
            )

        return events

    def get_events(self) -> List[Dict]:
        """今日を基準にイベントを取得（既存 API 互換用）"""
        return self.get_events_for_date(date.today())
