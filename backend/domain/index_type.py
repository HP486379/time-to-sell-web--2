from __future__ import annotations

import logging
from typing import Optional

CANONICAL_INDEX_TYPES = {
    "SP500",
    "SP500_JPY",
    "TOPIX",
    "NIKKEI225",
    "NIFTY50",
    "ALLCOUNTRY",
    "ALLCOUNTRY_JPY",
}

INDEX_TYPE_ALIASES = {
    "sp500": "SP500",
    "sp500_jpy": "SP500_JPY",
    "topix": "TOPIX",
    "nikkei": "NIKKEI225",
    "nikkei225": "NIKKEI225",
    "nikkei_225": "NIKKEI225",
    "nikkei-225": "NIKKEI225",
    "nifty50": "NIFTY50",
    "orukan": "ALLCOUNTRY",
    "allcountry": "ALLCOUNTRY",
    "orukan_jpy": "ALLCOUNTRY_JPY",
    "allcountry_jpy": "ALLCOUNTRY_JPY",
}


def normalize_index_type(
    value: object,
    *,
    default: Optional[str] = None,
    logger: Optional[logging.Logger] = None,
) -> str:
    """Normalize index type to canonical uppercase representation.

    If `default` is supplied, unknown/invalid values are warned and defaulted.
    Otherwise ValueError is raised for unknown values.
    """

    normalized: Optional[str] = None
    if isinstance(value, str):
        raw = value.strip()
        upper = raw.upper()
        lower = raw.lower()
        if upper in CANONICAL_INDEX_TYPES:
            normalized = upper
        else:
            normalized = INDEX_TYPE_ALIASES.get(lower)

    if normalized:
        return normalized

    if default is not None:
        if logger:
            logger.warning("Unknown index_type=%r; fallback to %s", value, default)
        return default

    raise ValueError(f"Invalid index_type: {value}")
