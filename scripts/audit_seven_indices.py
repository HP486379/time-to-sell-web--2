#!/usr/bin/env python3
"""Read-only audit of seven live evaluate responses. No account or paid UI required."""
import argparse
import datetime as dt
import json
import math
import time
import urllib.error
import urllib.request

INDICES = ("SP500", "SP500_JPY", "TOPIX", "NIKKEI225", "NIFTY50", "ALLCOUNTRY", "ALLCOUNTRY_JPY")


def fetch(url: str, index: str, timeout: int) -> dict:
    body = json.dumps({"index_type": index, "total_quantity": 0, "avg_cost": 0, "score_ma": 200}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read())
            return {"index": index, "elapsed_s": round(time.perf_counter() - started, 3),
                    "http": response.status, "payload": payload}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"index": index, "elapsed_s": round(time.perf_counter() - started, 3),
                "error": str(exc)}


def summarize(result: dict, now: dt.datetime) -> dict:
    row = {k: v for k, v in result.items() if k != "payload"}
    if "payload" not in result:
        return row
    data = result["payload"]
    if not isinstance(data, dict):
        row.update({"audit_error": "response_not_object", "payload_type": type(data).__name__})
        return row
    series = data.get("price_series") or []
    if not isinstance(series, list):
        series = []
    valid = []
    invalid_rows = []
    for number, point in enumerate(series):
        reason = None
        if not isinstance(point, dict):
            reason = "row_not_object"
        else:
            date_value = point.get("date")
            close = point.get("close")
            try:
                parsed_date = dt.date.fromisoformat(date_value) if isinstance(date_value, str) else None
                if not parsed_date or parsed_date.isoformat() != date_value:
                    reason = "invalid_date"
            except ValueError:
                reason = "invalid_date"
            if not reason and (isinstance(close, bool) or not isinstance(close, (int, float))
                               or not math.isfinite(close)):
                reason = "invalid_close"
        if reason:
            invalid_rows.append({"row": number, "reason": reason})
        else:
            valid.append(point)
    ordered = sorted(valid, key=lambda p: p["date"])
    last = ordered[-1] if ordered else {}
    last_date = last.get("date")
    try:
        days_old = (now.date() - dt.date.fromisoformat(last_date)).days if last_date else None
    except ValueError:
        days_old = None
    scores = data.get("scores")
    if not isinstance(scores, dict):
        scores = {}
    debug = data.get("debug")
    if not isinstance(debug, dict):
        debug = {}
    quality = data.get("quality")
    if not isinstance(quality, dict):
        quality = {}
    provider = data.get("adopted_provider") or debug.get("adopted_provider")
    symbol = (data.get("adopted_symbol") or debug.get("adopted_symbol")
              or debug.get("resolved_symbol"))
    audit_missing = []
    if not provider:
        audit_missing.append("adopted_provider")
    if not symbol:
        audit_missing.append("adopted_symbol")
    if not debug:
        audit_missing.append("debug_details_not_exposed")
    row.update({
        "status": data.get("status"), "reasons": data.get("reasons"),
        "score": scores.get("total"), "source": data.get("source"),
        "adopted_provider": provider, "adopted_symbol": symbol,
        "adoption_reason": debug.get("adoption_reason"),
        "quality": quality or None,
        "provider_reject_reasons": data.get("provider_reject_reasons") or debug.get("provider_reject_reasons"),
        "audit_missing_fields": audit_missing,
        "provider_verified": bool(provider and symbol),
        "as_of": data.get("as_of"), "rows": len(series), "valid_rows": len(valid),
        "invalid_rows": invalid_rows, "invalid_row_count": len(invalid_rows),
        "last_date": last_date, "last_close": last.get("close"),
        "calendar_days_old": days_old, "current_price": data.get("current_price"),
        "last_equals_current_price": (
            math.isclose(float(last["close"]), float(data["current_price"]), rel_tol=1e-8)
            if last and isinstance(data.get("current_price"), (float, int)) else None
        ),
    })
    return row


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="https://mai-rishi-kun.onrender.com")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", default="seven-index-audit.json")
    args = parser.parse_args()
    now = dt.datetime.now(dt.timezone.utc)
    results = []
    for attempt in range(1, args.rounds + 1):
        for index in INDICES:
            try:
                result = summarize(fetch(args.base.rstrip("/") + "/api/evaluate", index, args.timeout), now)
            except Exception as exc:
                result = {"index": index, "audit_error": "unexpected_audit_exception",
                          "error_type": type(exc).__name__, "error": str(exc)}
            result["round"] = attempt
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump({"checked_at_utc": now.isoformat(), "results": results}, output, ensure_ascii=False, indent=2)
    print("Saved:", args.output)
    print("Review freshness vs each index's exchange calendar; weekends/holidays are not errors by themselves.")


if __name__ == "__main__":
    main()
