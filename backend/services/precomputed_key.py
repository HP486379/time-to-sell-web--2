from __future__ import annotations


def build_precomputed_backtest_key(
    *,
    index_type: str,
    start_date_iso: str,
    end_date_iso: str,
    initial_cash: float,
    buy_threshold: float,
    sell_threshold: float,
    score_ma: int,
) -> str:
    return (
        f"{index_type}|{start_date_iso}|{end_date_iso}|"
        f"{float(initial_cash):.2f}|{float(buy_threshold):.2f}|{float(sell_threshold):.2f}|{int(score_ma)}"
    )

