from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
from datetime import date
from typing import Any

_RUNTIME_MAX_DAYS = int(os.getenv("BACKTEST_RUNTIME_MAX_DAYS", str(366 * 3)))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _long_runtime_guard_disabled() -> bool:
    # Precomputed generation intentionally runs long ranges locally.
    if _truthy(os.getenv("BACKTEST_ALLOW_LONG_RUNTIME")):
        return True
    if os.getenv("PRECOMPUTED_PRESETS") or os.getenv("PRECOMPUTED_TARGETS"):
        return True
    return any(str(arg).endswith("generate_precomputed_backtests.py") for arg in sys.argv)


def _raise_long_runtime_rejected(start_date: date, end_date: date, index_type: str) -> None:
    try:
        from fastapi import HTTPException
    except Exception as exc:  # pragma: no cover - FastAPI is present in API runtime.
        raise ValueError(
            "runtime_backtest_range_too_long:"
            f"index_type={index_type},requested_start={start_date.isoformat()},"
            f"end_date={end_date.isoformat()},max_runtime_days={_RUNTIME_MAX_DAYS}"
        ) from exc

    raise HTTPException(
        status_code=400,
        detail={
            "error": "runtime_backtest_range_too_long",
            "index_type": index_type,
            "requested_start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "max_runtime_days": _RUNTIME_MAX_DAYS,
            "message": "3年超のバックテストは事前計算済み期間のみ利用できます。",
        },
    )


def _patch_backtest_service(module: Any) -> None:
    service_cls = getattr(module, "BacktestService", None)
    if service_cls is None or getattr(service_cls, "_long_runtime_guard_installed", False):
        return

    original = service_cls.fetch_and_validate_price_history_for_backtest

    def guarded_fetch_and_validate(self, start_date: date, end_date: date, index_type: str):
        if (
            not _long_runtime_guard_disabled()
            and start_date is not None
            and end_date is not None
            and (end_date - start_date).days > _RUNTIME_MAX_DAYS
        ):
            _raise_long_runtime_rejected(start_date, end_date, index_type)
        return original(self, start_date, end_date, index_type)

    service_cls.fetch_and_validate_price_history_for_backtest = guarded_fetch_and_validate
    service_cls._long_runtime_guard_installed = True


class _BacktestServicePatchLoader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader):
        self._wrapped = wrapped

    def create_module(self, spec):
        create_module = getattr(self._wrapped, "create_module", None)
        if create_module is None:
            return None
        return create_module(spec)

    def exec_module(self, module):
        self._wrapped.exec_module(module)
        _patch_backtest_service(module)


class _BacktestServicePatchFinder(importlib.abc.MetaPathFinder):
    TARGET = "services.backtest_service"

    def find_spec(self, fullname, path=None, target=None):
        if fullname != self.TARGET:
            return None
        for finder in sys.meta_path:
            if finder is self:
                continue
            find_spec = getattr(finder, "find_spec", None)
            if find_spec is None:
                continue
            spec = find_spec(fullname, path, target)
            if spec is None or spec.loader is None:
                continue
            if not isinstance(spec.loader, _BacktestServicePatchLoader):
                spec.loader = _BacktestServicePatchLoader(spec.loader)
            return spec
        return None


if "services.backtest_service" in sys.modules:
    _patch_backtest_service(sys.modules["services.backtest_service"])
elif not any(isinstance(finder, _BacktestServicePatchFinder) for finder in sys.meta_path):
    sys.meta_path.insert(0, _BacktestServicePatchFinder())
