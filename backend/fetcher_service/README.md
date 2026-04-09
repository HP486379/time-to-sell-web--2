# fetcher_service

外部デプロイ前提の市場データ取得サービスです。  
`/fetch` を公開し、backend から `MARKET_FETCH_API_BASE` 経由で利用します。

## Local 起動

```bash
cd backend/fetcher_service
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 9000
```

## API

`GET /fetch`

query:
- `provider`: `stooq` | `yfinance` | `auto`
- `symbol`: 例 `NIKKEI225`
- `start`: `YYYY-MM-DD`
- `end`: `YYYY-MM-DD`

`start`/`end` を省略した場合は直近5年を自動選択します。

response:

```json
{
  "symbol": "NIKKEI225",
  "provider": "stooq",
  "prices": [
    { "date": "2026-04-01", "close": 37750.11 }
  ]
}
```

## Render デプロイ

`backend/fetcher_service/render.yaml` を使用して Python Web Service としてデプロイします。  
デプロイ後、backend 側の `MARKET_FETCH_API_BASE` に公開 URL を設定してください。
