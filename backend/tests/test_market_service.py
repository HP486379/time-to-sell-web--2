import pandas as pd
import yfinance as yf

from backend.services.sp500_market_service import SP500MarketService


def test_get_price_history_range_handles_dataframe(monkeypatch):
    service = SP500MarketService(symbol="TEST")

    dates = pd.date_range("2020-01-01", periods=3, freq="B")
    df = pd.DataFrame({"Close": [100.0, 101.5, 102.25]}, index=dates)

    def fake_download(symbol, start, end, interval):  # pragma: no cover - simple stub
        return df

    monkeypatch.setattr(yf, "download", fake_download)

    history = service.get_price_history_range(dates[0].date(), dates[-1].date(), allow_fallback=False)
    assert history == [
        (dates[0].date().isoformat(), 100.0),
        (dates[1].date().isoformat(), 101.5),
        (dates[2].date().isoformat(), 102.25),
    ]
