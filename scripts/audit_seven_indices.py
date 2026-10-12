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
    series = data.get("price_series") or []
    if not isinstance(series, list):
        series = []
    valid = [p for p in series if isinstance(p, dict) and isinstance(p.get("date"), str)
             and isinstance(p.get("close"), (int, float)) and math.isfinite(p["close"])]
    ordered = sorted(valid, key=lambda p: p["date"])
    last = ordered[-1] if ordered else {}
    last_date = last.get("date")
    try:
        days_old = (now.date() - dt.date.fromisoformat(last_date)).days if last_date else None
    except ValueError:
        days_old = None
    scores = data.get("scores") or {}
    debug = data.get("debug") or {}
    row.update({
        "status": data.get("status"), "reasons": data.get("reasons"),
        "score": scores.get("total"), "source": data.get("source"),
        "adopted_provider": data.get("adopted_provider") or debug.get("adopted_provider"),
        "adoption_reason": debug.get("adoption_reason"),
        "as_of": data.get("as_of"), "rows": len(series), "valid_rows": len(valid),
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
            result = summarize(fetch(args.base.rstrip("/") + "/api/evaluate", index, args.timeout), now)
            result["round"] = attempt
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    with open(args.output, "w", encoding="utf-8") as output:
        json.dump({"checked_at_utc": now.isoformat(), "results": results}, output, ensure_ascii=False, indent=2)
    print("Saved:", args.output)
    print("Review freshness vs each index's exchange calendar; weekends/holidays are not errors by themselves.")


if __name__ == "__main__":
    main()
