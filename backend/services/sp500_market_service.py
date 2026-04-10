import logging
import math
import os
import random
import statistics
import time
import json
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
import pandas as pd
import yfinance as yf
from dotenv import load_dotenv
from domain.index_type import normalize_index_type
from services.market_data_provider import (
    fetch_fx_from_stooq,
    fetch_history_from_nav_api,
    fetch_history_from_stooq,
    fetch_history_from_yfinance,
)


logger = logging.getLogger(__name__)


class SP500MarketService:
    """Service that fetches live pricing via yfinance with an optional synthetic fallback."""

    def __init__(self, symbol: Optional[str] = None):
        load_dotenv()
        self._yf_session = requests.Session()
        self._yf_session.trust_env = False
        self._yf_session.proxies.clear()
        self._yf_session.headers.update(
            {
                "User-Agent": os.getenv(
                    "MARKET_DATA_USER_AGENT",
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                )
            }
        )
        self.symbol_map = {
            "SP500": symbol or os.getenv("SP500_SYMBOL", "^GSPC"),
            "TOPIX": os.getenv("TOPIX_SYMBOL", "^TOPX"),
            "NIKKEI225": os.getenv("NIKKEI_SYMBOL", "^N225"),
            "NIFTY50": os.getenv("NIFTY50_SYMBOL", "^NSEI"),
            # オルカンは MSCI ACWI 連動 ETF（ACWI）をプロキシとして利用する
            "ALLCOUNTRY": os.getenv("ORUKAN_SYMBOL", "ACWI"),
            # オルカン円建ては ACWI × USD/JPY を用いる
            "ALLCOUNTRY_JPY": os.getenv("ORUKAN_JPY_SYMBOL", os.getenv("ORUKAN_SYMBOL", "ACWI")),
            # S&P500 円建ては ^GSPC × USD/JPY を用いる
            "SP500_JPY": os.getenv("SP500_JPY_SYMBOL", os.getenv("SP500_SYMBOL", "^GSPC")),
        }
        self.symbol_fallback_map = {
            "TOPIX": [os.getenv("TOPIX_SYMBOL_FALLBACK", "1306.T")],
            "NIFTY50": [
                os.getenv("NIFTY50_SYMBOL_FALLBACK", "NIFTYBEES.NS"),
                os.getenv("NIFTY50_SYMBOL_FALLBACK_2", "INDY"),
            ],
            "ALLCOUNTRY": [
                os.getenv("ORUKAN_SYMBOL_FALLBACK", "VT"),
                os.getenv("ORUKAN_SYMBOL_FALLBACK_2", "URTH"),
            ],
            "ALLCOUNTRY_JPY": [
                os.getenv("ORUKAN_JPY_SYMBOL_FALLBACK", os.getenv("ORUKAN_SYMBOL_FALLBACK", "VT")),
                os.getenv("ORUKAN_JPY_SYMBOL_FALLBACK_2", os.getenv("ORUKAN_SYMBOL_FALLBACK_2", "URTH")),
            ],
        }

        self.fx_symbol_map = {
            "ALLCOUNTRY_JPY": os.getenv("ORUKAN_JPY_FX_SYMBOL", "JPY=X"),
            "SP500_JPY": os.getenv("SP500_JPY_FX_SYMBOL", "JPY=X"),
        }
        self.fx_symbol_fallback_map = {
            "ALLCOUNTRY_JPY": [os.getenv("ORUKAN_JPY_FX_SYMBOL_FALLBACK", "USDJPY=X")],
            "SP500_JPY": [os.getenv("SP500_JPY_FX_SYMBOL_FALLBACK", "USDJPY=X")],
        }

        self.price_type_map = {
            "SP500": os.getenv("SP500_PRICE_TYPE", "index"),
            "TOPIX": os.getenv("TOPIX_PRICE_TYPE", "index"),
            "NIKKEI225": os.getenv("NIKKEI_PRICE_TYPE", "index"),
            "NIFTY50": os.getenv("NIFTY50_PRICE_TYPE", "index"),
            "ALLCOUNTRY": "index",
            "ALLCOUNTRY_JPY": "index_jpy",
            "SP500_JPY": "index_jpy",
        }

        self.nav_api_map = {
            "SP500": os.getenv("SP500_NAV_API_BASE"),
            "TOPIX": os.getenv("TOPIX_NAV_API_BASE"),
            "NIKKEI225": os.getenv("NIKKEI_NAV_API_BASE"),
            "NIFTY50": os.getenv("NIFTY50_NAV_API_BASE"),
        }

        self.allow_synth_map = {
            "SP500": self._flag("SP500_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "TOPIX": self._flag("TOPIX_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "NIKKEI225": self._flag("NIKKEI_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "NIFTY50": self._flag("NIFTY50_ALLOW_SYNTHETIC_FALLBACK", default=True),
            "ALLCOUNTRY": True,
            "ALLCOUNTRY_JPY": True,
            "SP500_JPY": True,
        }

        self.start_prices = {
            "SP500": 4000.0,
            "TOPIX": 1500.0,
            "NIKKEI225": 15000.0,
            "NIFTY50": 4000.0,
            "ALLCOUNTRY": 15000.0,
            # index_jpy は指数値×USD/JPY で桁が大きくなるため、妥当なスケールに合わせる
            "ALLCOUNTRY_JPY": 2000000.0,
            "SP500_JPY": 600000.0,
        }

        self._last_good_history: Dict[str, List[Tuple[str, float]]] = {}
        self._last_source: Dict[str, str] = {}
        self._last_debug: Dict[str, Dict[str, object]] = {}
        self._enable_cache = symbol != "TEST"
        self._cache_dir = Path(__file__).resolve().parent.parent / "data" / "cache"
        self._bootstrap_synth_flag_file = self._cache_dir / "bootstrap_synth_once.json"
        self._bootstrap_allow_synth_once = self._flag("BOOTSTRAP_ALLOW_SYNTHETIC_ONCE", default=True)
        self._force_stooq_only = self._flag("MARKET_FORCE_STOOQ_ONLY", default=False)
        self._last_good_max_stale_days = int(os.getenv("MARKET_LAST_GOOD_MAX_STALE_DAYS", "10"))
        if self._enable_cache:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_last_good_cache()

        logger.info(
            "[MARKET CONFIG] symbols=%s fx_symbols=%s fallback=%s price_types=%s",
            self.symbol_map,
            self.fx_symbol_map,
            self.allow_synth_map,
            self.price_type_map,
        )
        if self._force_stooq_only:
            logger.warning("[MARKET CONFIG] MARKET_FORCE_STOOQ_ONLY=true (stooq only mode)")

    def _cache_path(self, index_type: str) -> Path:
        return self._cache_dir / f"{index_type}.json"

    def _load_last_good_cache(self) -> None:
        for index_type in self.symbol_map.keys():
            path = self._cache_path(index_type)
            if not path.exists():
                continue
            try:
                payload = json.loads(path.read_text())
                history = payload.get("history")
                if not isinstance(history, list) or not history:
                    continue
                normalized = [(str(d), float(v)) for d, v in history]
                reason = self._validate_history(normalized, index_type)
                if reason:
                    logger.warning(
                        "Skip invalid last_good cache index=%s reason=%s",
                        index_type,
                        reason,
                    )
                    continue
                self._last_good_history[index_type] = normalized
                logger.info("Loaded last_good cache index=%s points=%d", index_type, len(normalized))
            except Exception as exc:
                logger.warning("Failed loading cache index=%s path=%s err=%s", index_type, path, exc)

    def _persist_last_good_cache(self, index_type: str, *, source_hint: Optional[str] = None) -> None:
        if not self._enable_cache:
            return
        source = source_hint or self.get_last_source(index_type)
        confidence = self.get_source_confidence(source)
        debug = self._last_debug.get(index_type, {})
        validation_reason = str(debug.get("validation_reason") or "")
        if confidence == "low" or "LOW_QUALITY_DATA" in validation_reason:
            logger.warning("Skip persisting last_good index=%s source=%s validation=%s", index_type, source, validation_reason)
            return
        path = self._cache_path(index_type)
        history = self._last_good_history.get(index_type)
        if not history:
            return
        payload = {
            "index_type": index_type,
            "history": history,
            "source": source,
            "quality_summary": debug.get("quality_summary", ""),
            "saved_at": date.today().isoformat(),
        }
        path.write_text(json.dumps(payload, ensure_ascii=False))

    def _mark_bootstrap_synth_used(self, index_type: str) -> None:
        if not self._enable_cache:
            return
        used = set()
        if self._bootstrap_synth_flag_file.exists():
            try:
                used = set(json.loads(self._bootstrap_synth_flag_file.read_text()).get("used", []))
            except Exception:
                used = set()
        used.add(index_type)
        self._bootstrap_synth_flag_file.write_text(json.dumps({"used": sorted(list(used))}, ensure_ascii=False))

    def _is_bootstrap_synth_used(self, index_type: str) -> bool:
        if not self._enable_cache:
            return False
        if not self._bootstrap_synth_flag_file.exists():
            return False
        try:
            used = set(json.loads(self._bootstrap_synth_flag_file.read_text()).get("used", []))
            return index_type in used
        except Exception:
            return False

    def _normalize_index_type(self, index_type: str) -> str:
        return normalize_index_type(index_type, default="SP500", logger=logger)

    def _extract_close_series(self, hist: pd.DataFrame) -> pd.Series:
        """Extract a 1-D close/adj close series from yfinance DataFrame."""

        close = hist.get("Close")
        if close is None:
            close = hist.get("Adj Close")
        if close is None:
            raise ValueError("close column missing")
        # yfinance may return a DataFrame when using MultiIndex columns; squeeze to Series
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        return close.dropna()

    def _flag(self, name: str, default: bool = False) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        return raw.lower() in {"1", "true", "yes", "on"}

    def _resolve_symbol(self, index_type: str) -> str:
        index_type = self._normalize_index_type(index_type)
        return self.symbol_map.get(index_type, self.symbol_map["SP500"])

    def _resolve_symbol_candidates(self, index_type: str) -> List[str]:
        index_type = self._normalize_index_type(index_type)
        primary = self._resolve_symbol(index_type)
        fallbacks = self.symbol_fallback_map.get(index_type, [])
        candidates = [primary, *fallbacks]
        deduped: List[str] = []
        for symbol in candidates:
            if symbol and symbol not in deduped:
                deduped.append(symbol)
        return deduped

    def _set_last_source(self, index_type: str, source: str) -> None:
        index_type = self._normalize_index_type(index_type)
        self._last_source[index_type] = source
        self._last_debug.setdefault(index_type, {})["source"] = source
        self._last_debug.setdefault(index_type, {})["source_confidence"] = self.get_source_confidence(source)
        logger.info("Market source decided index=%s source=%s", index_type, source)

    def get_last_source(self, index_type: str) -> str:
        index_type = self._normalize_index_type(index_type)
        return self._last_source.get(index_type, "real")

    def get_source_confidence(self, source: str) -> str:
        confidence_map = {
            "stooq": "high",
            "nav_api": "high",
            "yfinance": "medium",
            "last_good": "medium",
            "bootstrap": "medium",
            "synthetic": "low",
        }
        return confidence_map.get(source, "medium")

    def _set_debug(self, index_type: str, **kwargs) -> None:
        index_type = self._normalize_index_type(index_type)
        self._last_debug.setdefault(index_type, {}).update(kwargs)

    def _record_provider_attempt(
        self,
        index_type: str,
        *,
        provider: str,
        success: bool,
        history: Optional[List[Tuple[str, float]]] = None,
        validation_reason: Optional[str] = None,
        quality_result: Optional[str] = None,
        fetch_error: Optional[str] = None,
        validation_result: Optional[str] = None,
        adopted: Optional[bool] = None,
        symbol: Optional[str] = None,
        fx_symbol: Optional[str] = None,
    ) -> None:
        index_type = self._normalize_index_type(index_type)
        self._last_debug.setdefault(index_type, {}).setdefault("provider_reject_reasons", [])
        first_close: Optional[float] = None
        last_close: Optional[float] = None
        if history:
            first_close = float(history[0][1])
            last_close = float(history[-1][1])
        ratio: Optional[float] = None
        if first_close is not None and first_close > 0 and last_close is not None:
            ratio = last_close / first_close
        attempts = self._last_debug.setdefault(index_type, {}).get("provider_attempts")
        attempt_list: List[Dict[str, object]] = list(attempts) if isinstance(attempts, list) else []
        if adopted is None:
            adopted = success
        if validation_result is None:
            validation_result = "passed" if success else "failed"
        if quality_result is None and success:
            quality_result = "success"
        if fetch_error is None and validation_reason and validation_reason.startswith("fetch_error:"):
            fetch_error = validation_reason.split("fetch_error:", 1)[1]
        attempt_list.append(
            {
                "provider": provider,
                "success": success,
                "first_close": first_close,
                "last_close": last_close,
                "ratio": ratio,
                "validation_passed": validation_reason is None,
                "validation_result": validation_result,
                "reject_reason": validation_reason,
                "quality_result": quality_result,
                "fetch_error": fetch_error,
                "adopted": adopted,
                "symbol": symbol,
                "fx_symbol": fx_symbol,
            }
        )
        self._last_debug.setdefault(index_type, {})["provider_attempts"] = attempt_list

    def get_last_debug(self, index_type: str) -> Dict[str, object]:
        index_type = self._normalize_index_type(index_type)
        return dict(self._last_debug.get(index_type, {}))

    def _resolve_fx_symbol(self, index_type: str) -> Optional[str]:
        index_type = self._normalize_index_type(index_type)
        return self.fx_symbol_map.get(index_type)

    def _resolve_fx_symbol_candidates(self, index_type: str) -> List[str]:
        index_type = self._normalize_index_type(index_type)
        primary = self._resolve_fx_symbol(index_type)
        fallbacks = self.fx_symbol_fallback_map.get(index_type, [])
        candidates = [primary, *fallbacks]
        deduped: List[str] = []
        for symbol in candidates:
            if symbol and symbol not in deduped:
                deduped.append(symbol)
        return deduped

    def _resolve_nav_base(self, index_type: str) -> Optional[str]:
        index_type = self._normalize_index_type(index_type)
        return self.nav_api_map.get(index_type)

    def _allow_synthetic_for_index(self, index_type: str) -> bool:
        index_type = self._normalize_index_type(index_type)
        return self.allow_synth_map.get(index_type, True)

    def _resolve_price_type(self, index_type: str) -> Optional[str]:
        index_type = self._normalize_index_type(index_type)
        return self.price_type_map.get(index_type)

    def _download_close_series(self, symbol: str, start: date, end: date) -> pd.Series:
        return fetch_history_from_yfinance(symbol, start, end, session=self._yf_session)

    def _validate_history(self, history: List[Tuple[str, float]], index_type: str) -> Optional[str]:
        index_type = self._normalize_index_type(index_type)
        first_price = history[0][1] if history else None
        last_price = history[-1][1] if history else None
        ratio: Optional[float] = None
        if first_price is not None and first_price > 0 and last_price is not None:
            ratio = float(last_price) / float(first_price)

        def reject(reason: str) -> str:
            logger.warning(
                "Validation reject index=%s first_close=%s last_close=%s ratio=%s reason=%s",
                index_type,
                first_price,
                last_price,
                f"{ratio:.6f}" if ratio is not None else None,
                reason,
            )
            return reason

        if not history:
            return reject("empty_history")

        # スケール判定は絶対価格ではなく ratio を使用する。
        # 通常レンジ: 0.2 < ratio < 5.0（ここは reject ではなくログのみ）
        # reject は明らかな異常値のみに限定する。
        if first_price is None or first_price <= 0:
            return reject(f"invalid_first_close:{first_price}")
        if last_price is None or last_price <= 0:
            return reject(f"invalid_last_close:{last_price}")
        if ratio is None:
            return reject("invalid_ratio:none")
        if ratio < 0.2 or ratio > 5.0:
            logger.info(
                "Validation soft-range index=%s first_close=%s last_close=%s ratio=%.6f range=(0.2,5.0)",
                index_type,
                first_price,
                last_price,
                ratio,
            )
        if ratio < 0.1:
            return reject(f"abnormal_ratio_low:ratio={ratio:.6f}<min=0.100000")
        if ratio > 10.0:
            return reject(f"abnormal_ratio_high:ratio={ratio:.6f}>max=10.000000")

        return None

    def _quality_check_history(self, history: List[Tuple[str, float]]) -> Tuple[str, List[str]]:
        if not history:
            return "hard_ng", ["LOW_POINTS(points=0)"]
        if len(history) < 50:
            return "hard_ng", [f"LOW_POINTS(points={len(history)})"]

        values: List[float] = []
        nan_count = 0
        for _, value in history:
            if value is None:
                nan_count += 1
                continue
            if isinstance(value, float) and math.isnan(value):
                nan_count += 1
                continue
            values.append(float(value))

        if not values:
            return "hard_ng", ["HIGH_NAN_RATIO(nan_ratio=1.00)"]
        if len(set(values)) == 1:
            return "hard_ng", [f"TOO_FLAT(flat_days={len(history)})"]

        soft_flags: List[str] = []
        if nan_count > 0:
            nan_ratio = nan_count / max(1, len(history))
            soft_flags.append(f"HIGH_NAN_RATIO(nan_ratio={nan_ratio:.2f})")
        if len(history) < 200:
            soft_flags.append(f"LOW_POINTS(points={len(history)})")

        # 連続同値が長い場合は劣化扱い
        prev_value: Optional[float] = None
        flat_run = 1
        max_flat_run = 1
        for value in values:
            if prev_value is not None:
                if abs(value - prev_value) < 1e-9:
                    flat_run += 1
                    max_flat_run = max(max_flat_run, flat_run)
                else:
                    flat_run = 1
            prev_value = value
        if max_flat_run > 30:
            soft_flags.append(f"TOO_FLAT(flat_days={max_flat_run})")

        if len(history) >= 252:
            base_1y = history[-252][1]
            last = history[-1][1]
            if base_1y and base_1y > 0:
                one_year_return = (last / base_1y - 1.0) * 100.0
                if one_year_return < -80.0 or one_year_return > 200.0:
                    soft_flags.append(f"ABNORMAL_RETURN(return={one_year_return:+.2f}%)")

        if soft_flags:
            return "soft_ng", soft_flags
        return "ok", []

    def _quality_check_index_jpy(
        self,
        *,
        base_points: int,
        fx_points: int,
        combined_points: int,
    ) -> Tuple[str, List[str]]:
        if base_points < 50:
            return "hard_ng", [f"LOW_POINTS(points={base_points})"]
        if fx_points < 50:
            return "hard_ng", [f"LOW_POINTS(points={fx_points})"]
        if combined_points < 50:
            return "hard_ng", [f"LOW_POINTS(points={combined_points})"]

        denom = min(base_points, fx_points) if min(base_points, fx_points) > 0 else 1
        missing_ratio = 1.0 - (combined_points / denom)
        if missing_ratio >= 0.50:
            return "hard_ng", [f"HIGH_NAN_RATIO(nan_ratio={missing_ratio:.2f})"]

        soft_flags: List[str] = []
        if base_points < 200:
            soft_flags.append(f"LOW_POINTS(points={base_points})")
        if fx_points < 200:
            soft_flags.append(f"LOW_POINTS(points={fx_points})")
        if combined_points < 200:
            soft_flags.append(f"LOW_POINTS(points={combined_points})")
        if missing_ratio >= 0.10:
            soft_flags.append(f"HIGH_NAN_RATIO(nan_ratio={missing_ratio:.2f})")

        if soft_flags:
            return "soft_ng", soft_flags
        return "ok", []

    def _quality_summary(self, flags: List[str]) -> str:
        if not flags:
            return "QUALITY_OK"
        return " | ".join(flags)

    def _update_last_good_history(
        self,
        index_type: str,
        history: List[Tuple[str, float]],
        *,
        source_hint: Optional[str] = None,
    ) -> None:
        index_type = self._normalize_index_type(index_type)
        self._last_good_history[index_type] = [(d, round(float(v), 2)) for d, v in history]
        self._persist_last_good_cache(index_type, source_hint=source_hint)

    def _add_provider_reject_reason(self, index_type: str, reason: str) -> None:
        index_type = self._normalize_index_type(index_type)
        current = self._last_debug.setdefault(index_type, {}).get("provider_reject_reasons")
        reasons: List[str] = list(current) if isinstance(current, list) else []
        reasons.append(reason)
        self._last_debug.setdefault(index_type, {})["provider_reject_reasons"] = reasons

    def _get_valid_last_good_history(self, index_type: str) -> Optional[List[Tuple[str, float]]]:
        index_type = self._normalize_index_type(index_type)
        history = self._last_good_history.get(index_type)
        if not history:
            self._set_debug(index_type, last_good_reject_reason="missing")
            return None
        ok, checks = self._evaluate_last_good_eligibility(index_type, history)
        self._set_debug(
            index_type,
            last_good_date=checks.get("last_good_date"),
            last_good_age_days=checks.get("age_days"),
            last_good_freshness_ok=checks.get("freshness_ok"),
            last_good_quality_check=checks.get("quality_check"),
            last_good_tail_check=checks.get("tail_check"),
            last_good_reject_reason=checks.get("reject_reason"),
        )
        if not ok:
            logger.warning("Ignore broken last_good index=%s reason=%s", index_type, checks.get("reject_reason"))
            return None
        self._set_debug(index_type, last_good_reject_reason=None)
        return history

    def _evaluate_last_good_eligibility(
        self, index_type: str, history: List[Tuple[str, float]]
    ) -> Tuple[bool, Dict[str, object]]:
        last_good_date = history[-1][0] if history else None
        age_days: Optional[int] = None
        freshness_ok = False
        try:
            if last_good_date:
                parsed = date.fromisoformat(str(last_good_date))
                age_days = max(0, (date.today() - parsed).days)
                freshness_ok = age_days <= self._last_good_max_stale_days
        except Exception:
            freshness_ok = False
        if not freshness_ok:
            return False, {
                "last_good_date": last_good_date,
                "age_days": age_days,
                "freshness_ok": False,
                "quality_check": {"result": "failed", "reason": "stale_or_invalid_date"},
                "tail_check": {"result": "unknown", "reason": None},
                "reject_reason": f"last_good_stale_or_invalid:max_age_days={self._last_good_max_stale_days}",
            }

        reason = self._validate_history(history, index_type)
        if reason:
            return False, {
                "last_good_date": last_good_date,
                "age_days": age_days,
                "freshness_ok": True,
                "quality_check": {"result": "failed", "reason": reason},
                "tail_check": {"result": "failed", "reason": reason},
                "reject_reason": reason,
            }

        provider_reason = self._provider_acceptance_reason(history)
        tail_reason = provider_reason if provider_reason and "tail_outlier" in provider_reason else None
        if provider_reason:
            return False, {
                "last_good_date": last_good_date,
                "age_days": age_days,
                "freshness_ok": True,
                "quality_check": {"result": "failed", "reason": provider_reason},
                "tail_check": {"result": "failed" if tail_reason else "passed", "reason": tail_reason},
                "reject_reason": provider_reason,
            }

        quality_status, quality_reason = self._quality_check_history(history)
        if quality_status != "ok":
            summary = self._quality_summary(quality_reason)
            return False, {
                "last_good_date": last_good_date,
                "age_days": age_days,
                "freshness_ok": True,
                "quality_check": {"result": "failed", "reason": summary},
                "tail_check": {"result": "passed", "reason": None},
                "reject_reason": f"last_good_quality_ng:{summary}",
            }

        return True, {
            "last_good_date": last_good_date,
            "age_days": age_days,
            "freshness_ok": True,
            "quality_check": {"result": "success", "reason": None},
            "tail_check": {"result": "passed", "reason": None},
            "reject_reason": None,
        }

    def _provider_acceptance_reason(self, history: List[Tuple[str, float]]) -> Optional[str]:
        points = len(history)
        if points < 200:
            return f"provider_reject_points:points={points}<200"
        values = [v for _, v in history]
        nan_count = sum(1 for v in values if v is None or (isinstance(v, float) and math.isnan(v)))
        if nan_count > 0:
            return f"provider_reject_nan:nan_count={nan_count}"
        max_jump = 0.0
        prev: Optional[float] = None
        for value in values:
            current = float(value)
            if prev is not None and prev > 0:
                jump = abs((current - prev) / prev)
                max_jump = max(max_jump, jump)
            prev = current
        if max_jump > 0.15:
            return f"provider_reject_abnormal_jump:max_jump={max_jump:.4f}>0.1500"
        first = float(values[0])
        last = float(values[-1])
        if first and first > 0:
            total_return = (last / first - 1.0) * 100.0
            if total_return < -90.0 or total_return > 400.0:
                return f"provider_reject_abnormal_total_change:return={total_return:.2f}%"
        if len(values) >= 25:
            recent = float(values[-1])
            prev_window = [float(v) for v in values[-21:-1]]
            if prev_window:
                recent_median = statistics.median(prev_window)
                if recent_median > 0:
                    tail_ratio = recent / recent_median
                    if tail_ratio < 0.70 or tail_ratio > 1.30:
                        return f"provider_reject_tail_outlier:tail_ratio={tail_ratio:.4f}"
        return None

    def _log_validation_failure(
        self,
        *,
        index_type: str,
        symbol: str,
        price_type: Optional[str],
        reason: str,
        attempt: int,
        history: List[Tuple[str, float]],
    ) -> None:
        last_price = history[-1][1] if history else None
        logger.warning(
            "Validation failed index=%s symbol=%s price_type=%s reason=%s attempt=%d points=%d last=%s",
            index_type,
            symbol,
            price_type,
            reason,
            attempt,
            len(history),
            last_price,
        )

    def _get_validated_index_jpy_history(
        self,
        start: date,
        end: date,
        index_type: str,
        *,
        allow_low_quality: bool = False,
    ) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        symbol = self._resolve_symbol(index_type)
        price_type = self._resolve_price_type(index_type)
        backoffs = [0.2, 0.5, 1.0]
        last_error: Optional[Exception] = None

        for attempt, delay in enumerate(backoffs, start=1):
            try:
                series = self._fetch_index_history_jpy(
                    start,
                    end,
                    index_type,
                    allow_low_quality=allow_low_quality,
                )
                reason = self._validate_history(series, index_type)
                if not reason:
                    self._record_provider_attempt(
                        index_type,
                        provider="yfinance",
                        success=True,
                        history=series,
                        symbol=symbol,
                    )
                    self._update_last_good_history(index_type, series, source_hint=self.get_last_source(index_type))
                    return series
                self._record_provider_attempt(
                    index_type,
                    provider="yfinance",
                    success=False,
                    history=series,
                    validation_reason=reason,
                    symbol=symbol,
                )
                self._log_validation_failure(
                    index_type=index_type,
                    symbol=symbol,
                    price_type=price_type,
                    reason=reason,
                    attempt=attempt,
                    history=series,
                )
                self._set_debug(index_type, validation_reason=reason)
                self._add_provider_reject_reason(index_type, f"index_jpy:{symbol}:{reason}")
                last_error = ValueError(reason)
            except Exception as exc:
                self._record_provider_attempt(
                    index_type,
                    provider="yfinance",
                    success=False,
                    validation_reason=f"fetch_error:{exc}",
                    symbol=symbol,
                )
                self._add_provider_reject_reason(index_type, f"index_jpy:{symbol}:fetch_error:{exc}")
                last_error = exc
                self._set_debug(index_type, fetch_error=str(exc))
                logger.warning(
                    "Index JPY history fetch failed index=%s symbol=%s price_type=%s attempt=%d error=%s",
                    index_type,
                    symbol,
                    price_type,
                    attempt,
                    exc,
                )
            if attempt < len(backoffs):
                time.sleep(delay)

        last_good = self._get_valid_last_good_history(index_type)
        if last_good:
            logger.info(
                "Using last good history index=%s symbol=%s price_type=%s points=%d last=%s",
                index_type,
                symbol,
                price_type,
                len(last_good),
                last_good[-1][1] if last_good else None,
            )
            self._set_last_source(index_type, "last_good")
            self._set_debug(
                index_type,
                adopted_provider="last_good",
                adoption_reason="last_good",
                quality_check={"symbol": symbol, "result": "last_good_adopted", "reason": None},
            )
            return last_good

        if last_error:
            raise ValueError("data_unavailable") from last_error
        raise ValueError("data_unavailable")

    def _fetch_yfinance_history_with_retry(
        self,
        start: date,
        end: date,
        index_type: str,
        *,
        enforce_quality: bool = True,
    ) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        symbol_candidates = self._resolve_symbol_candidates(index_type)
        symbol = symbol_candidates[0]
        price_type = self._resolve_price_type(index_type)
        backoffs = [0.2, 0.5, 1.0]
        last_error: Optional[Exception] = None
        tried_symbols: List[str] = []

        for attempt, delay in enumerate(backoffs, start=1):
            for candidate_symbol in symbol_candidates:
                symbol = candidate_symbol
                if symbol not in tried_symbols:
                    tried_symbols.append(symbol)
                try:
                    closes = self._download_close_series(symbol, start, end)
                    history = [(self._to_iso_date(idx), round(float(val), 2)) for idx, val in closes.items()]
                    reason = self._validate_history(history, index_type)
                    if not reason:
                        if enforce_quality:
                            provider_reason = self._provider_acceptance_reason(history)
                            if provider_reason:
                                logger.warning(
                                    "Provider reject index=%s provider=yfinance symbol=%s reason=%s",
                                    index_type,
                                    symbol,
                                    provider_reason,
                                )
                                self._add_provider_reject_reason(index_type, f"yfinance:{symbol}:{provider_reason}")
                                self._record_provider_attempt(
                                    index_type,
                                    provider="yfinance",
                                    success=False,
                                    history=history,
                                    validation_reason=provider_reason,
                                    quality_result="provider_reject",
                                    validation_result="failed",
                                    adopted=False,
                                    symbol=symbol,
                                )
                                last_error = ValueError(provider_reason)
                                continue
                            quality_status, quality_reason = self._quality_check_history(history)
                            if quality_status == "hard_ng":
                                summary = self._quality_summary(quality_reason)
                                self._set_debug(
                                    index_type,
                                    quality_flags=quality_reason,
                                    quality_summary=summary,
                                    quality_check={"symbol": symbol, "result": "quality_ng", "reason": summary},
                                )
                                logger.warning(
                                    "Candidate quality NG index=%s symbol=%s result=quality_ng reason=%s",
                                    index_type,
                                    symbol,
                                    summary,
                                )
                                self._record_provider_attempt(
                                    index_type,
                                    provider="yfinance",
                                    success=False,
                                    history=history,
                                    validation_reason=summary,
                                    quality_result="hard_ng",
                                    validation_result="failed",
                                    adopted=False,
                                    symbol=symbol,
                                )
                                self._add_provider_reject_reason(index_type, f"yfinance:{symbol}:{summary}")
                                last_error = ValueError(summary)
                                continue
                            if quality_status == "soft_ng":
                                summary = self._quality_summary(quality_reason)
                                degrade_reason = f"LOW_QUALITY_DATA:{summary}"
                                source = "real" if symbol == symbol_candidates[0] else "fallback_degraded"
                                self._set_debug(
                                    index_type,
                                    validation_reason=degrade_reason,
                                    quality_flags=quality_reason,
                                    quality_summary=summary,
                                )
                            else:
                                source = "real" if symbol == symbol_candidates[0] else "real_fallback"
                        else:
                            source = "real" if symbol == symbol_candidates[0] else "real_fallback"
                        logger.info(
                            "Using yfinance history for %s (symbol=%s price_type=%s points=%d tried_symbols=%s source=%s)",
                            index_type,
                            symbol,
                            price_type,
                            len(history),
                            tried_symbols,
                            source,
                        )
                        self._record_provider_attempt(
                            index_type,
                            provider="yfinance",
                            success=True,
                            history=history,
                            quality_result="ok" if (not enforce_quality or quality_status == "ok") else "soft_ng_adopted",
                            validation_result="passed",
                            adopted=True,
                            symbol=symbol,
                        )
                        self._update_last_good_history(index_type, history, source_hint=source)
                        self._set_last_source(index_type, source)
                        self._set_debug(
                            index_type,
                            tried_symbols=tried_symbols,
                            adopted_provider="yfinance",
                            adopted_symbol=symbol,
                            adoption_reason="primary" if symbol == symbol_candidates[0] else "fallback",
                            quality_check={
                                "symbol": symbol,
                                "result": "success" if not enforce_quality or quality_status == "ok" else "soft_ng_adopted",
                                "reason": self._quality_summary(quality_reason) if enforce_quality and quality_status == "soft_ng" else None,
                            },
                            fetch_error=None,
                        )
                        return history
                    self._log_validation_failure(
                        index_type=index_type,
                        symbol=symbol,
                        price_type=price_type,
                        reason=reason,
                        attempt=attempt,
                        history=history,
                    )
                    self._record_provider_attempt(
                        index_type,
                        provider="yfinance",
                        success=False,
                        history=history,
                        validation_reason=reason,
                        quality_result="validation_ng",
                        validation_result="failed",
                        adopted=False,
                        symbol=symbol,
                    )
                    self._set_debug(index_type, validation_reason=reason)
                    self._add_provider_reject_reason(index_type, f"yfinance:{symbol}:{reason}")
                    last_error = ValueError(reason)
                except Exception as exc:
                    self._record_provider_attempt(
                        index_type,
                        provider="yfinance",
                        success=False,
                        validation_reason=f"fetch_error:{exc}",
                        quality_result="fetch_error",
                        fetch_error=str(exc),
                        validation_result="failed",
                        adopted=False,
                        symbol=symbol,
                    )
                    self._add_provider_reject_reason(index_type, f"yfinance:{symbol}:fetch_error:{exc}")
                    last_error = exc
                    self._set_debug(index_type, fetch_error=str(exc))
                    logger.warning(
                        "Price history attempt failed index=%s symbol=%s price_type=%s attempt=%d error=%s",
                        index_type,
                        symbol,
                        price_type,
                        attempt,
                        exc,
                    )
            if attempt < len(backoffs):
                time.sleep(delay)

        last_good = self._get_valid_last_good_history(index_type)
        if last_good:
            logger.info(
                "Using last good history index=%s symbol=%s price_type=%s points=%d last=%s",
                index_type,
                symbol,
                price_type,
                len(last_good),
                last_good[-1][1] if last_good else None,
            )
            self._set_last_source(index_type, "last_good")
            self._set_debug(
                index_type,
                adopted_provider="last_good",
                adoption_reason="last_good",
                quality_check={"symbol": symbol, "result": "last_good_adopted", "reason": None},
            )
            return last_good

        if last_error:
            logger.warning(
                "No real history resolved index=%s tried_symbols=%s",
                index_type,
                tried_symbols,
            )
            self._set_debug(index_type, tried_symbols=tried_symbols)
            raise ValueError("data_unavailable") from last_error
        raise ValueError("data_unavailable")

    def _fetch_index_history_jpy(
        self,
        start: date,
        end: date,
        index_type: str,
        *,
        allow_low_quality: bool = False,
    ) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        symbol_candidates = self._resolve_symbol_candidates(index_type)
        fx_symbol_candidates = self._resolve_fx_symbol_candidates(index_type)
        if not fx_symbol_candidates:
            raise ValueError("fx_symbol required for index_jpy")

        tried_symbols: List[str] = []
        tried_fx_symbols: List[str] = []
        last_error: Optional[Exception] = None

        for symbol in symbol_candidates:
            if symbol not in tried_symbols:
                tried_symbols.append(symbol)
            try:
                idx_close = self._download_close_series(symbol, start, end).rename("close_usd")
            except Exception as exc:
                last_error = exc
                self._set_debug(index_type, fetch_error=str(exc))
                logger.warning("JPY candidate failed index=%s symbol=%s result=failed error=%s", index_type, symbol, exc)
                continue

            for fx_symbol in fx_symbol_candidates:
                if fx_symbol not in tried_fx_symbols:
                    tried_fx_symbols.append(fx_symbol)
                try:
                    fx_close = self._download_close_series(fx_symbol, start, end).rename("usdjpy")
                    combined = pd.concat([idx_close, fx_close], axis=1, join="inner").dropna()
                    if combined.empty:
                        self._set_debug(index_type, fetch_error="no overlapping dates for index and fx", combined_points=0)
                        last_error = ValueError("no overlapping dates for index and fx")
                        self._record_provider_attempt(
                            index_type,
                            provider="yfinance",
                            success=False,
                            validation_reason="no_overlapping_dates",
                            symbol=symbol,
                            fx_symbol=fx_symbol,
                        )
                        self._add_provider_reject_reason(
                            index_type,
                            f"yfinance:{symbol}+{fx_symbol}:no_overlapping_dates",
                        )
                        logger.warning(
                            "JPY candidate quality NG index=%s symbol=%s fx_symbol=%s result=quality_ng reason=no_overlapping_dates",
                            index_type,
                            symbol,
                            fx_symbol,
                        )
                        continue

                    combined["close"] = combined["close_usd"] * combined["usdjpy"]
                    series = [(self._to_iso_date(idx), round(float(val), 2)) for idx, val in combined["close"].items()]
                    quality_status, quality_reason = self._quality_check_index_jpy(
                        base_points=len(idx_close),
                        fx_points=len(fx_close),
                        combined_points=len(combined),
                    )
                    if quality_status == "hard_ng":
                        summary = self._quality_summary(quality_reason)
                        self._record_provider_attempt(
                            index_type,
                            provider="yfinance",
                            success=False,
                            history=series,
                            validation_reason=summary,
                            symbol=symbol,
                            fx_symbol=fx_symbol,
                        )
                        self._add_provider_reject_reason(index_type, f"yfinance:{symbol}+{fx_symbol}:{summary}")
                        self._set_debug(
                            index_type,
                            quality_flags=quality_reason,
                            quality_summary=summary,
                            quality_check={"symbol": symbol, "fx_symbol": fx_symbol, "result": "quality_ng", "reason": summary},
                        )
                        logger.warning(
                            "JPY candidate quality NG index=%s symbol=%s fx_symbol=%s result=quality_ng reason=%s base_points=%d fx_points=%d combined_points=%d",
                            index_type,
                            symbol,
                            fx_symbol,
                            summary,
                            len(idx_close),
                            len(fx_close),
                            len(combined),
                        )
                        last_error = ValueError(summary)
                        continue
                    source = "real"
                    if symbol != symbol_candidates[0] or fx_symbol != fx_symbol_candidates[0]:
                        source = "real_fallback"
                    if quality_status == "soft_ng":
                        source = "fallback_degraded"
                        summary = self._quality_summary(quality_reason)
                        self._set_debug(
                            index_type,
                            validation_reason=f"LOW_QUALITY_DATA:{summary}",
                            quality_flags=quality_reason,
                            quality_summary=summary,
                        )
                        if not allow_low_quality:
                            last_error = ValueError(summary)
                            self._add_provider_reject_reason(
                                index_type,
                                f"yfinance:{symbol}+{fx_symbol}:LOW_QUALITY_DATA:{summary}",
                            )
                            self._record_provider_attempt(
                                index_type,
                                provider="yfinance",
                                success=False,
                                history=series,
                                validation_reason=f"LOW_QUALITY_DATA:{summary}",
                                symbol=symbol,
                                fx_symbol=fx_symbol,
                            )
                            continue
                    logger.info(
                        "Using yfinance history for %s (symbol=%s fx_symbol=%s price_type=%s points=%d tried_symbols=%s tried_fx_symbols=%s source=%s)",
                        index_type,
                        symbol,
                        fx_symbol,
                        self._resolve_price_type(index_type),
                        len(series),
                        tried_symbols,
                        tried_fx_symbols,
                        source,
                    )
                    self._record_provider_attempt(
                        index_type,
                        provider="yfinance",
                        success=True,
                        history=series,
                        symbol=symbol,
                        fx_symbol=fx_symbol,
                    )
                    self._set_last_source(index_type, source)
                    self._set_debug(
                        index_type,
                        adopted_provider="yfinance",
                        fetch_error=None,
                        combined_points=len(series),
                        tried_symbols=tried_symbols,
                        tried_fx_symbols=tried_fx_symbols,
                        adopted_symbol=symbol,
                        adopted_fx_symbol=fx_symbol,
                        adoption_reason=(
                            "primary"
                            if symbol == symbol_candidates[0] and fx_symbol == fx_symbol_candidates[0]
                            else "fallback"
                        ),
                        quality_check={
                            "symbol": symbol,
                            "fx_symbol": fx_symbol,
                            "result": "success" if quality_status == "ok" else "soft_ng_adopted",
                            "reason": self._quality_summary(quality_reason) if quality_status == "soft_ng" else None,
                        },
                    )
                    return series
                except Exception as exc:
                    self._record_provider_attempt(
                        index_type,
                        provider="yfinance",
                        success=False,
                        validation_reason=f"fetch_error:{exc}",
                        symbol=symbol,
                        fx_symbol=fx_symbol,
                    )
                    self._add_provider_reject_reason(index_type, f"yfinance:{symbol}+{fx_symbol}:fetch_error:{exc}")
                    last_error = exc
                    self._set_debug(index_type, fetch_error=str(exc))
                    logger.warning(
                        "JPY candidate failed index=%s symbol=%s fx_symbol=%s result=failed error=%s",
                        index_type,
                        symbol,
                        fx_symbol,
                        exc,
                    )
                    continue

        self._set_debug(index_type, tried_symbols=tried_symbols, tried_fx_symbols=tried_fx_symbols)
        logger.warning(
            "No real index_jpy history resolved index=%s tried_symbols=%s tried_fx_symbols=%s",
            index_type,
            tried_symbols,
            tried_fx_symbols,
        )
        if last_error:
            raise ValueError("data_unavailable") from last_error
        raise ValueError("data_unavailable")

    def _fetch_nav_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        """Optional custom NAV API (if provided by env) returning date/close pairs."""
        index_type = self._normalize_index_type(index_type)

        nav_base = self._resolve_nav_base(index_type)
        if not nav_base:
            self._record_provider_attempt(
                index_type,
                provider="nav_api",
                success=False,
                validation_reason="not_configured",
                symbol=self._resolve_symbol(index_type),
            )
            return []

        symbol = self._resolve_symbol(index_type)
        price_type = self._resolve_price_type(index_type)

        try:
            series = fetch_history_from_nav_api(nav_base, symbol, str(price_type), start, end)
            nav_reason = self._validate_history(series, index_type)
            if nav_reason:
                self._record_provider_attempt(
                    index_type,
                    provider="nav_api",
                    success=False,
                    history=series,
                    validation_reason=nav_reason,
                    symbol=symbol,
                )
                self._add_provider_reject_reason(index_type, f"nav_api:{symbol}:{nav_reason}")
                logger.warning("NAV API invalid index=%s symbol=%s reason=%s", index_type, symbol, nav_reason)
                return []
            self._record_provider_attempt(
                index_type,
                provider="nav_api",
                success=True,
                history=series,
                symbol=symbol,
            )
            logger.info(
                "[NAV API] index=%s symbol=%s price_type=%s points=%d",
                index_type,
                symbol,
                price_type,
                len(series),
            )
            return series
        except Exception as exc:
            self._record_provider_attempt(
                index_type,
                provider="nav_api",
                success=False,
                validation_reason=f"fetch_error:{exc}",
                symbol=symbol,
            )
            self._add_provider_reject_reason(index_type, f"nav_api:{symbol}:fetch_error:{exc}")
            logger.warning("NAV API fallback due to error: %s", exc)
        return []

    def _fetch_stooq_history_with_validation(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        symbol = self._resolve_symbol(index_type)
        closes = fetch_history_from_stooq(symbol, start, end)
        history = [(self._to_iso_date(idx), round(float(v), 2)) for idx, v in closes.items()]
        reason = self._validate_history(history, index_type)
        provider_reason = self._provider_acceptance_reason(history)
        if reason or provider_reason:
            msg = provider_reason or reason
            self._record_provider_attempt(
                index_type,
                provider="stooq",
                success=False,
                history=history,
                validation_reason=msg,
                symbol=symbol,
            )
            self._add_provider_reject_reason(index_type, f"stooq:{symbol}:{msg}")
            raise ValueError(msg)
        self._record_provider_attempt(
            index_type,
            provider="stooq",
            success=True,
            history=history,
            symbol=symbol,
        )
        self._set_last_source(index_type, "stooq")
        self._update_last_good_history(index_type, history, source_hint="stooq")
        self._set_debug(
            index_type,
            tried_providers=["stooq"],
            adopted_provider="stooq",
            adopted_symbol=symbol,
            fetch_error=None,
            quality_check={"symbol": symbol, "result": "success", "reason": None},
        )
        logger.info("provider=stooq index=%s symbol=%s result=adopted points=%d", index_type, symbol, len(history))
        return history

    def _fetch_sp500_with_provider_priority(self, start: date, end: date) -> List[Tuple[str, float]]:
        index_type = "SP500"
        tried_providers: List[str] = []
        nav_hist = self._fetch_nav_history(start, end, index_type)
        if nav_hist:
            tried_providers.append("nav_api")
            self._set_last_source(index_type, "nav_api")
            self._update_last_good_history(index_type, nav_hist, source_hint="nav_api")
            self._set_debug(
                index_type,
                tried_providers=tried_providers,
                adopted_provider="nav_api",
                adopted_symbol=self._resolve_symbol(index_type),
                fetch_error=None,
                quality_check={"symbol": self._resolve_symbol(index_type), "result": "success", "reason": None},
            )
            return nav_hist
        tried_providers.append("nav_api")
        self._set_debug(index_type, tried_providers=tried_providers)

        symbol = self._resolve_symbol(index_type)
        try:
            closes = fetch_history_from_stooq(symbol, start, end)
            hist = [(self._to_iso_date(idx), round(float(v), 2)) for idx, v in closes.items()]
            reason = self._validate_history(hist, index_type)
            provider_reason = self._provider_acceptance_reason(hist)
            if not reason and not provider_reason:
                self._record_provider_attempt(
                    index_type,
                    provider="stooq",
                    success=True,
                    history=hist,
                    symbol=symbol,
                )
                self._set_last_source(index_type, "stooq")
                self._update_last_good_history(index_type, hist, source_hint="stooq")
                self._set_debug(
                    index_type,
                    tried_providers=tried_providers + ["stooq"],
                    adopted_provider="stooq",
                    adopted_symbol=symbol,
                    fetch_error=None,
                    quality_check={"symbol": symbol, "result": "success", "reason": None},
                )
                return hist
            self._record_provider_attempt(
                index_type,
                provider="stooq",
                success=False,
                history=hist,
                validation_reason=provider_reason or reason,
                symbol=symbol,
            )
            logger.warning(
                "Provider reject index=%s provider=stooq symbol=%s reason=%s",
                index_type,
                symbol,
                provider_reason or reason,
            )
            self._add_provider_reject_reason(index_type, f"stooq:{symbol}:{provider_reason or reason}")
        except Exception as exc:
            self._record_provider_attempt(
                index_type,
                provider="stooq",
                success=False,
                validation_reason=f"fetch_error:{exc}",
                symbol=symbol,
            )
            self._add_provider_reject_reason(index_type, f"stooq:{symbol}:fetch_error:{exc}")
        tried_providers.append("stooq")
        self._set_debug(index_type, tried_providers=tried_providers)

        hist = self._fetch_yfinance_history_with_retry(start, end, index_type)
        self._set_debug(index_type, tried_providers=tried_providers + ["yfinance"])
        return hist

    def _fetch_sp500_jpy_with_provider_priority(self, start: date, end: date) -> List[Tuple[str, float]]:
        index_type = "SP500_JPY"
        tried_providers: List[str] = []
        base_symbol = self._resolve_symbol(index_type)
        fx_symbol = self._resolve_fx_symbol(index_type) or "JPY=X"
        try:
            base = fetch_history_from_stooq(base_symbol, start, end).rename("close_usd")
            fx = fetch_fx_from_stooq(fx_symbol, start, end).rename("usdjpy")
            combined = pd.concat([base, fx], axis=1, join="inner").dropna()
            if len(combined) >= 50:
                combined["close"] = combined["close_usd"] * combined["usdjpy"]
                hist = [(self._to_iso_date(idx), round(float(v), 2)) for idx, v in combined["close"].items()]
                provider_reason = self._provider_acceptance_reason(hist)
                if not provider_reason:
                    self._record_provider_attempt(
                        index_type,
                        provider="stooq",
                        success=True,
                        history=hist,
                        symbol=base_symbol,
                        fx_symbol=fx_symbol,
                    )
                    self._set_last_source(index_type, "stooq")
                    self._update_last_good_history(index_type, hist, source_hint="stooq")
                    self._set_debug(
                        index_type,
                        tried_providers=["stooq"],
                        adopted_provider="stooq",
                        adopted_symbol=base_symbol,
                        adopted_fx_symbol=fx_symbol,
                        fetch_error=None,
                        quality_check={"symbol": base_symbol, "fx_symbol": fx_symbol, "result": "success", "reason": None},
                    )
                    return hist
                self._record_provider_attempt(
                    index_type,
                    provider="stooq",
                    success=False,
                    history=hist,
                    validation_reason=provider_reason,
                    symbol=base_symbol,
                    fx_symbol=fx_symbol,
                )
                logger.warning(
                    "Provider reject index=%s provider=stooq symbol=%s fx_symbol=%s reason=%s",
                    index_type,
                    base_symbol,
                    fx_symbol,
                    provider_reason,
                )
                self._add_provider_reject_reason(index_type, f"stooq:{base_symbol}+{fx_symbol}:{provider_reason}")
        except Exception as exc:
            self._record_provider_attempt(
                index_type,
                provider="stooq",
                success=False,
                validation_reason=f"fetch_error:{exc}",
                symbol=base_symbol,
                fx_symbol=fx_symbol,
            )
            self._add_provider_reject_reason(index_type, f"stooq:{base_symbol}+{fx_symbol}:fetch_error:{exc}")
        tried_providers.append("stooq")
        self._set_debug(index_type, tried_providers=tried_providers)

        hist = self._get_validated_index_jpy_history(start, end, index_type)
        self._set_debug(index_type, tried_providers=tried_providers + ["yfinance"])
        return hist

    def _fallback_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        """決定的で過度に膨らまないシンセティック履歴を生成する。

        * 年率のドリフトは指数ごとに設定（S&P500: 約7%、TOPIX: 約4%）
        * 日次の揺らぎを小さめに入れて最大ドローダウンが0%にならないようにする
        * 週末はスキップし、営業日ベースで積み上げる
        """

        index_type = self._normalize_index_type(index_type)
        base_index_map = {
            "SP500_JPY": "SP500",
            "ALLCOUNTRY_JPY": "ALLCOUNTRY",
        }
        if index_type in base_index_map:
            base_history = self._fallback_history(start, end, base_index_map[index_type])
            fx_history = self._fallback_fx_history(start, end, index_type)
            fx_by_date = {d: v for d, v in fx_history}
            combined = [
                (d, round(price * fx_by_date[d], 2))
                for d, price in base_history
                if d in fx_by_date
            ]
            if combined:
                return combined

        annual_drift_map = {
            "SP500": 0.07,
            "TOPIX": 0.04,
            "NIKKEI225": 0.05,
            "NIFTY50": 0.08,
            "ALLCOUNTRY": 0.06,
            "ALLCOUNTRY_JPY": 0.06,
            "SP500_JPY": 0.07,
        }
        annual_drift = annual_drift_map.get(index_type, 0.05)
        daily_drift = annual_drift / 260.0

        rng_seed = f"{index_type}:{start.isoformat()}:{end.isoformat()}"
        rng = random.Random(rng_seed)

        history: List[Tuple[str, float]] = []
        price = self.start_prices.get(index_type, 4000.0)
        noise_span = 0.003 if index_type == "TOPIX" else 0.006

        current = start
        while current <= end:
            if current.weekday() < 5:  # 月〜金のみ
                noise = rng.uniform(-noise_span, noise_span)
                # 半年ごとに5%程度の調整を入れて drawdown を作る（TOPIXは除外）
                if index_type != "TOPIX" and (current.timetuple().tm_yday // 182) % 2 == 1:
                    noise -= 0.002

                daily_change = 1 + daily_drift + noise
                price = max(1.0, price * daily_change)
                history.append((current.isoformat(), round(price, 2)))
            current += timedelta(days=1)

        return history

    def _fallback_fx_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        start_fx_map = {
            "SP500_JPY": 150.0,
            "ALLCOUNTRY_JPY": 150.0,
        }
        fx = start_fx_map.get(index_type, 150.0)
        rng_seed = f"fx:{index_type}:{start.isoformat()}:{end.isoformat()}"
        rng = random.Random(rng_seed)

        history: List[Tuple[str, float]] = []
        current = start
        while current <= end:
            if current.weekday() < 5:
                # 日次 ±0.2% 程度の為替揺らぎ
                fx = max(50.0, fx * (1 + rng.uniform(-0.002, 0.002)))
                history.append((current.isoformat(), round(fx, 4)))
            current += timedelta(days=1)
        return history

    def _fallback_quality_reason(self, history: List[Tuple[str, float]], index_type: str) -> Optional[str]:
        if not history:
            return "fallback_empty"
        index_type = self._normalize_index_type(index_type)
        quality_status, quality_reason = self._quality_check_history(history)
        if quality_status == "hard_ng":
            return self._quality_summary(quality_reason)
        start_price = self.start_prices.get(index_type)
        first = history[0][1]
        last = history[-1][1]
        soft_reason: Optional[str] = None
        if quality_status == "soft_ng":
            soft_reason = self._quality_summary(quality_reason)
        if start_price and last < start_price * 0.6:
            if soft_reason:
                return f"SOFT:{soft_reason},fallback_too_low:{last:.2f}<{start_price * 0.6:.2f}"
            return f"SOFT:fallback_too_low:{last:.2f}<{start_price * 0.6:.2f}"
        if first > 0:
            five_year_return = (last / first - 1.0) * 100.0
            if five_year_return <= -50.0:
                if soft_reason:
                    return f"SOFT:{soft_reason},fallback_5y_return_too_low:{five_year_return:.2f}%"
                return f"SOFT:fallback_5y_return_too_low:{five_year_return:.2f}%"
        if soft_reason:
            return f"SOFT:{soft_reason}"
        return None

    def _build_valid_fallback_history(self, start: date, end: date, index_type: str) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        fallback = self._fallback_history(start, end, index_type)
        if index_type == "TOPIX":
            self._set_debug(index_type, quality_check={"type": "synthetic_fallback", "result": "success", "reason": "topix_bypass"})
            return fallback
        reason = self._fallback_quality_reason(fallback, index_type)
        if not reason:
            self._set_debug(index_type, quality_check={"type": "synthetic_fallback", "result": "success"})
            return fallback
        if reason.startswith("SOFT:"):
            raw = reason.removeprefix("SOFT:")
            normalized = raw.replace(",", " | ")
            flags = [part.strip() for part in normalized.split("|") if part.strip()]
            summary = self._quality_summary(flags)
            low_quality_reason = f"LOW_QUALITY_DATA:{summary}"
            self._set_debug(
                index_type,
                validation_reason=low_quality_reason,
                quality_flags=flags,
                quality_summary=summary,
                quality_check={"type": "synthetic_fallback", "result": "soft_ng_adopted", "reason": low_quality_reason},
                adoption_reason="fallback",
            )
            return fallback

        logger.warning("Fallback quality check failed index=%s reason=%s", index_type, reason)
        self._set_debug(
            index_type,
            validation_reason=reason,
            quality_check={"type": "synthetic_fallback", "result": "quality_ng", "reason": reason},
        )
        if index_type in self._last_good_history:
            last_good = self._last_good_history[index_type]
            logger.info("Using last good history after fallback quality fail index=%s points=%d", index_type, len(last_good))
            self._set_last_source(index_type, "last_good")
            self._set_debug(index_type, adoption_reason="last_good")
            return last_good
        raise ValueError("data_unavailable")

    def _to_iso_date(self, idx) -> str:
        try:
            return idx.date().isoformat()
        except AttributeError:
            try:
                # pandas Timestamp may expose .to_pydatetime
                return idx.to_pydatetime().date().isoformat()  # type: ignore[attr-defined]
            except Exception:
                return str(idx)

    def get_price_history(
        self,
        index_type: str = "SP500",
        allow_synthetic: bool = False,
        allow_low_quality: bool = False,
    ) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        today = date.today()
        start = today - timedelta(days=365 * 5)
        allow_synth = self._allow_synthetic_for_index(index_type)
        self._set_debug(
            index_type,
            normalized_index_type=index_type,
            symbol=self._resolve_symbol(index_type),
            fx_symbol=self._resolve_fx_symbol(index_type),
            price_type=self._resolve_price_type(index_type),
            fetch_error=None,
            validation_reason=None,
            points=0,
            first_close=None,
            last_close=None,
            one_year_return=None,
            combined_points=None,
            quality_flags=[],
            quality_summary="",
            tried_providers=[],
            adopted_provider=None,
            provider_reject_reasons=[],
            provider_attempts=[],
        )
        try:
            if index_type == "SP500":
                return self._fetch_sp500_with_provider_priority(start, today)
            if index_type == "SP500_JPY":
                return self._fetch_sp500_jpy_with_provider_priority(start, today)

            price_type = self._resolve_price_type(index_type)
            if price_type == "index_jpy":
                return self._get_validated_index_jpy_history(
                    start,
                    today,
                    index_type,
                    allow_low_quality=allow_low_quality,
                )
            if self._force_stooq_only:
                return self._fetch_stooq_history_with_validation(start, today, index_type)

            nav_hist = self._fetch_nav_history(start, today, index_type)
            if nav_hist:
                nav_hist = [(d, round(v, 2)) for d, v in nav_hist]
                nav_reason = self._validate_history(nav_hist, index_type)
                if not nav_reason:
                    logger.info(
                        "Using NAV history for %s (symbol=%s price_type=%s points=%d)",
                        index_type,
                        self._resolve_symbol(index_type),
                        price_type,
                        len(nav_hist),
                    )
                    self._update_last_good_history(index_type, nav_hist, source_hint="real")
                    self._set_last_source(index_type, "real")
                    self._set_debug(
                        index_type,
                        adopted_provider="nav_api",
                        adopted_symbol=self._resolve_symbol(index_type),
                        fetch_error=None,
                        quality_check={"symbol": self._resolve_symbol(index_type), "result": "success", "reason": None},
                    )
                    return nav_hist
                self._log_validation_failure(
                    index_type=index_type,
                    symbol=self._resolve_symbol(index_type),
                    price_type=price_type,
                    reason=nav_reason,
                    attempt=1,
                    history=nav_hist,
                )

            return self._fetch_yfinance_history_with_retry(
                start,
                today,
                index_type,
                enforce_quality=not allow_low_quality,
            )
        except Exception as exc:
            self._set_debug(index_type, fetch_error=str(exc))
            logger.warning("Price history fetch failed (%s)", exc, exc_info=True)
            last_good = self._get_valid_last_good_history(index_type)
            if last_good:
                logger.info(
                    "Using last good history after fetch failure index=%s symbol=%s price_type=%s points=%d last=%s",
                    index_type,
                    self._resolve_symbol(index_type),
                    self._resolve_price_type(index_type),
                    len(last_good),
                    last_good[-1][1] if last_good else None,
                )
                self._set_last_source(index_type, "last_good")
                return last_good
            if not allow_synthetic and self._bootstrap_allow_synth_once and not self._is_bootstrap_synth_used(index_type):
                bootstrap = self._fallback_history(start, today, index_type)
                if bootstrap:
                    logger.warning(
                        "Bootstrap synthetic seed used once index=%s points=%d",
                        index_type,
                        len(bootstrap),
                    )
                    self._update_last_good_history(index_type, bootstrap, source_hint="bootstrap")
                    self._mark_bootstrap_synth_used(index_type)
                    self._set_last_source(index_type, "bootstrap")
                    self._set_debug(index_type, adoption_reason="bootstrap_seed")
                    return bootstrap
            if not allow_synth or not allow_synthetic:
                raise
            fallback = self._build_valid_fallback_history(start, today, index_type)
            if index_type == "TOPIX":
                self._update_last_good_history(index_type, fallback, source_hint="fallback")
            logger.info(
                "Using synthetic history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                self._resolve_symbol(index_type),
                self._resolve_price_type(index_type),
                len(fallback),
            )
            if index_type == "TOPIX":
                source = "fallback"
            else:
                source = "synthetic"
            self._set_last_source(index_type, source)
            return fallback
        finally:
            history = self._last_good_history.get(index_type)
            if history:
                first = history[0][1]
                last = history[-1][1]
                one_year_return = None
                if len(history) >= 252:
                    base_1y = history[-252][1]
                    if base_1y > 0:
                        one_year_return = round((last / base_1y - 1.0) * 100.0, 2)
                self._set_debug(
                    index_type,
                    points=len(history),
                    first_close=first,
                    last_close=last,
                    one_year_return=one_year_return,
                )

    def get_price_history_range(
        self, start: date, end: date, allow_fallback: bool = True, index_type: str = "SP500"
    ) -> List[Tuple[str, float]]:
        index_type = self._normalize_index_type(index_type)
        allow_synth = self._allow_synthetic_for_index(index_type)
        fallback_allowed = allow_fallback and allow_synth
        try:
            price_type = self._resolve_price_type(index_type)
            if price_type == "index_jpy":
                return self._get_validated_index_jpy_history(start, end, index_type)

            nav_hist = self._fetch_nav_history(start, end, index_type)
            if nav_hist:
                nav_hist = [(d, round(v, 2)) for d, v in nav_hist]
                nav_reason = self._validate_history(nav_hist, index_type)
                if not nav_reason:
                    logger.info(
                        "Using NAV history for %s (symbol=%s price_type=%s points=%d)",
                        index_type,
                        self._resolve_symbol(index_type),
                        price_type,
                        len(nav_hist),
                    )
                    self._update_last_good_history(index_type, nav_hist, source_hint="real")
                    self._set_last_source(index_type, "real")
                    self._set_debug(
                        index_type,
                        adopted_provider="nav_api",
                        adopted_symbol=self._resolve_symbol(index_type),
                        fetch_error=None,
                        quality_check={"symbol": self._resolve_symbol(index_type), "result": "success", "reason": None},
                    )
                    return nav_hist
                self._log_validation_failure(
                    index_type=index_type,
                    symbol=self._resolve_symbol(index_type),
                    price_type=price_type,
                    reason=nav_reason,
                    attempt=1,
                    history=nav_hist,
                )

            return self._fetch_yfinance_history_with_retry(start, end, index_type, enforce_quality=False)
        except Exception as exc:
            logger.warning("Price history fetch failed (%s)", exc, exc_info=True)
            last_good = self._get_valid_last_good_history(index_type)
            if last_good:
                logger.info(
                    "Using last good history after fetch failure index=%s symbol=%s price_type=%s points=%d last=%s",
                    index_type,
                    self._resolve_symbol(index_type),
                    self._resolve_price_type(index_type),
                    len(last_good),
                    last_good[-1][1] if last_good else None,
                )
                self._set_last_source(index_type, "last_good")
                return last_good
            if not fallback_allowed:
                raise
            fallback = self._build_valid_fallback_history(start, end, index_type)
            logger.info(
                "Using synthetic history for %s (symbol=%s price_type=%s points=%d)",
                index_type,
                self._resolve_symbol(index_type),
                self._resolve_price_type(index_type),
                len(fallback),
            )
            if index_type == "TOPIX":
                source = "fallback"
            else:
                source = "synthetic"
            self._set_last_source(index_type, source)
            return fallback

    def get_usd_jpy(self) -> float:
        try:
            fx = yf.download("JPY=X", period="5d", interval="1d")
            fx = fx.dropna()
            if not fx.empty:
                return round(float(fx["Close"].iloc[-1]), 4)
        except Exception:
            pass
        return 150.0

    def get_fund_nav_jpy(self, sp_price_usd: float, usd_jpy: float) -> float:
        """
        eMAXIS Slim 米国株式（S&P500）の直近基準価額を取得する。

        Yahoo! Finance 上のファンドコード（デフォルト: 03311187.T）を優先し、
        取得できない場合は S&P500 指数を為替で円換算した値でフォールバックする。
        """

        fund_symbol = os.getenv("SP500_FUND_SYMBOL", "03311187.T")
        try:
            fund = yf.download(fund_symbol, period="1mo", interval="1d")
            fund = fund.dropna()
            if not fund.empty:
                return round(float(fund["Close"].iloc[-1]), 2)
        except Exception:
            pass

        return round(sp_price_usd * usd_jpy, 2)

    def get_current_price(
        self, history: Optional[List[Tuple[str, float]]] = None, index_type: str = "SP500"
    ) -> float:
        index_type = self._normalize_index_type(index_type)
        price_type = self._resolve_price_type(index_type)
        try:
            if price_type == "index_jpy":
                symbol = self._resolve_symbol(index_type)
                fx_symbol = self._resolve_fx_symbol(index_type)
                ticker = yf.Ticker(symbol)
                fx_ticker = yf.Ticker(fx_symbol) if fx_symbol else None
                live = ticker.fast_info.get("lastPrice") if ticker.fast_info else None
                fx_live = fx_ticker.fast_info.get("lastPrice") if fx_ticker and fx_ticker.fast_info else None
                if live and fx_live:
                    return round(float(live) * float(fx_live), 2)

                hist = ticker.history(period="5d", interval="1d")
                fx_hist = fx_ticker.history(period="5d", interval="1d") if fx_ticker else None
                if not hist.empty and fx_hist is not None and not fx_hist.empty:
                    return round(float(hist["Close"].iloc[-1]) * float(fx_hist["Close"].iloc[-1]), 2)
            else:
                ticker = yf.Ticker(self._resolve_symbol(index_type))
                live = ticker.fast_info.get("lastPrice") if ticker.fast_info else None
                if live:
                    return round(float(live), 2)
                hist = ticker.history(period="5d", interval="1d")
                if not hist.empty:
                    return round(float(hist["Close"].iloc[-1]), 2)
        except Exception:
            pass

        if history:
            return history[-1][1]
        today = date.today()
        synthetic = self._fallback_history(today - timedelta(days=30), today, index_type)
        return synthetic[-1][1]

    def build_price_series_with_ma(self, history: List[Tuple[str, float]]):
        closes = [p[1] for p in history]
        dates = [p[0] for p in history]

        def moving_avg(window: int) -> List[Optional[float]]:
            results: List[Optional[float]] = []
            running_sum = 0.0
            for i, price in enumerate(closes):
                running_sum += price
                if i >= window:
                    running_sum -= closes[i - window]
                if i + 1 >= window:
                    results.append(round(running_sum / window, 2))
                else:
                    results.append(None)
            return results

        ma20 = moving_avg(20)
        ma60 = moving_avg(60)
        ma200 = moving_avg(200)

        series = []
        for idx, date_str in enumerate(dates):
            series.append(
                {
                    "date": date_str,
                    "close": closes[idx],
                    "ma20": ma20[idx],
                    "ma60": ma60[idx],
                    "ma200": ma200[idx],
                }
            )
        return series
