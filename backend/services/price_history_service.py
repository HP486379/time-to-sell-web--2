import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Dict, List, Tuple

from services.sp500_market_service import SP500MarketService

logger = logging.getLogger(__name__)


class PriceHistoryFetchError(RuntimeError):
    pass


@dataclass
class CacheEntry:
    data: List[Tuple[str, float]]
    fetched_at: datetime


class PriceHistoryService:
    def __init__(
        self,
        market_service: SP500MarketService,
        ttl: timedelta = timedelta(minutes=15),
        max_retries: int = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self._market_service = market_service
        self._ttl = ttl
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._cache: Dict[str, CacheEntry] = {}

    def _cache_key(self, index_type: str, start: date, end: date) -> str:
        return f"{index_type}:{start.isoformat()}:{end.isoformat()}"

    def get_history(self, index_type: str, start: date, end: date) -> List[Tuple[str, float]]:
        key = self._cache_key(index_type, start, end)
        now = datetime.utcnow()
        cached = self._cache.get(key)

        if cached and now - cached.fetched_at < self._ttl:
            logger.info("[price_history] cache hit index=%s key=%s", index_type, key)
            return cached.data

        logger.info("[price_history] cache miss index=%s key=%s", index_type, key)
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            try:
                history = self._market_service.get_price_history_range(
                    start, end, allow_fallback=True, index_type=index_type
                )
                if not history:
                    raise ValueError("empty price history")
                self._cache[key] = CacheEntry(data=history, fetched_at=now)
                logger.info(
                    "[price_history] fetch success index=%s points=%d attempt=%d",
                    index_type,
                    len(history),
                    attempt,
                )
                return history
            except Exception as exc:  # noqa: BLE001 - keep context for retries
                last_error = exc
                logger.warning(
                    "[price_history] fetch failed index=%s attempt=%d error=%s",
                    index_type,
                    attempt,
                    exc,
                )
                if attempt < self._max_retries:
                    time.sleep(self._retry_delay)

        if cached:
            age = now - cached.fetched_at
            logger.warning(
                "[price_history] returning stale cache index=%s age=%s error=%s",
                index_type,
                age,
                last_error,
            )
            return cached.data

        raise PriceHistoryFetchError(str(last_error) if last_error else "price history fetch failed")
