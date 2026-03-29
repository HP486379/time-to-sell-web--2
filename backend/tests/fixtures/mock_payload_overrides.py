def apply_overrides(payload: dict) -> dict:
    # プロジェクト実装に合わせて、存在する場合だけ上書きする
    if "symbol" in payload:
        payload["symbol"] = "SPY"

    if "index_type" in payload:
        payload["index_type"] = payload.get("index_type") or "SP500"

    if "position" in payload and isinstance(payload["position"], dict):
        pos = payload["position"]
        if "entry_date" in pos:
            pos["entry_date"] = "2020-01-01"
        if "entry_price" in pos:
            pos["entry_price"] = 100.0
        if "quantity" in pos:
            pos["quantity"] = 1.0

    return payload
