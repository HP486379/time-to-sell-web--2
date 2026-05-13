from __future__ import annotations
import json
from datetime import date
from pathlib import Path
import os

from services.sp500_market_service import SP500MarketService
from services.macro_data_service import MacroDataService
from services.event_service import EventService
from services.backtest_service import BacktestService

OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "precomputed_backtests"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TARGETS = [
    ("SP500", date(2004,1,1), date(2025,12,31)),
    ("TOPIX", date(2014,1,1), date(2025,12,31)),
    ("NIKKEI225", date(2014,1,1), date(2025,12,31)),
    ("ALLCOUNTRY_JPY", date(2014,1,1), date(2025,12,31)),
]

def key(index_type, start_date, end_date, initial_cash, buy_threshold, sell_threshold, score_ma):
    return f"{index_type}|{start_date.isoformat()}|{end_date.isoformat()}|{float(initial_cash):.2f}|{float(buy_threshold):.2f}|{float(sell_threshold):.2f}|{int(score_ma)}"

if __name__ == "__main__":
    market = SP500MarketService()
    macro = MacroDataService()
    events = EventService()
    service = BacktestService(market, macro, events)
    initial_cash=100000.0; buy_threshold=40.0; sell_threshold=80.0; score_ma=200
    for index_type, start_date, end_date in TARGETS:
        result = service.run_backtest(start_date, end_date, initial_cash, buy_threshold, sell_threshold, index_type, score_ma, debug=False)
        payload = {
            "precomputed_key": key(index_type,start_date,end_date,initial_cash,buy_threshold,sell_threshold,score_ma),
            "generated_at": date.today().isoformat(),
            "logic_version": "v1",
            "git_commit": os.getenv("GIT_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or "unknown",
            "result": result,
        }
        fn = f"{index_type.lower()}_{start_date.isoformat()}_{end_date.isoformat()}_sell80_buy40_ma200.json"
        (OUT_DIR / fn).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        print("wrote", fn)
