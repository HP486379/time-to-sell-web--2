# S&P500 売り時ダッシュボード v1

ブラウザで動作する React + TypeScript（Vite）フロントエンドと、FastAPI バックエンドで構成された SPA です。

## 前提
- Node.js 18 以降
- Python 3.10 以降

## バックエンドの起動
1. 依存関係をインストール
   ```bash
   cd backend
   python -m venv .venv
   source .venv/bin/activate  # Windows は .venv\\Scripts\\activate
   pip install -r requirements.txt
   ```
2. 開発サーバーを起動
   ```bash
   uvicorn main:app --reload --host 0.0.0.0 --port 8000
   ```
3. 動作確認
   - ヘルスチェック: http://localhost:8000/api/health

### データソース設定
- 対象インデックス
  - S&P500: `.env` に `SP500_SYMBOL=VOO` などを指定（デフォルトは `^GSPC`）。
  - TOPIX: `.env` に `TOPIX_SYMBOL=1306.T`（TOPIX ETF）を指定（デフォルトも 1306.T）。
  - 日経225: `.env` に `NIKKEI_SYMBOL=^N225`（デフォルト）
  - NIFTY50: `.env` に `NIFTY50_SYMBOL=^NSEI`（デフォルト）
  - オルカン（USD建て）: `.env` に `ORUKAN_SYMBOL=ACWI`（MSCI ACWI 連動 ETF をプロキシとして使用）
  - オルカン（円建て）: `.env` に `ORUKAN_JPY_SYMBOL=ACWI` と `ORUKAN_JPY_FX_SYMBOL=JPY=X`（USD/JPY 終値で円換算）
- 実データ取得元
  - 株価・指数: yfinance（S&P500 / TOPIX / 日経225 / NIFTY50 / オルカン の終値を取得。オルカン円建ては ACWI × USD/JPY で計算）
  - NAV API がある場合（任意）: `SP500_NAV_API_BASE` / `TOPIX_NAV_API_BASE` / `NIKKEI_NAV_API_BASE` / `NIFTY50_NAV_API_BASE` を設定すると、`<base>/history?symbol=...` を優先利用
  - マクロ指標: FRED (`FRED_API_KEY` がある場合) → 無い場合は yfinance の代替 → それでも取得できなければ決定的なダミー値
- 重要イベント: ローカル算出（FOMC=第3水曜、CPI=月10日目安、雇用統計=月初の金曜を JST 日付のまま採用）。`backend/services/event_service.py` のヒューリスティックカレンダーをそのまま UI/ログに `source=local heuristic calendar` として出力し、日付は JST（+09:00）で ISO 表記に固定してタイムゾーンずれを防いでいます。
- バックテストのフォールバック制御（疑似データを許可する場合）
  - 取得失敗時に決定的な疑似系列へ切り替えるには、真偽値として解釈される値（`1` / `true` / `yes` / `on`）をセットしてください。
    - `BACKTEST_ALLOW_FALLBACK=1`（バックテスト時にフォールバックを許可するか）
    - `SP500_ALLOW_SYNTHETIC_FALLBACK=1` / `TOPIX_ALLOW_SYNTHETIC_FALLBACK=1` / `NIKKEI_ALLOW_SYNTHETIC_FALLBACK=1` / `NIFTY50_ALLOW_SYNTHETIC_FALLBACK=1`（指数ごとに疑似価格履歴を許可するか）
  - いずれかが 0/false の場合はその指数でフォールバックせず、外部データ取得に失敗すると 502 を返します。メッセージ: `external data unavailable (check network / API key / symbol)`
- 基準価額（円）の取得:
  - 参考基準価額: `GET /api/nav/sp500-synthetic`（S&P500 × USD/JPY）
  - eMAXIS Slim 米国株式（S&P500）基準価額: `GET /api/nav/emaxis-slim-sp500`（取得できない場合は参考値で代替）
- シンプルバックテスト（閾値売買）:
- `POST /api/backtest` に `{ "start_date": "2004-01-01", "end_date": "2024-12-31", "initial_cash": 1000000, "buy_threshold": 40, "sell_threshold": 80, "index_type": "SP500" }` のように渡すと、
    日次のスコアに基づく BUY/SELL 履歴とポートフォリオ推移、単純ホールド比較を返します（`index_type` は `SP500` / `TOPIX` / `NIKKEI` / `NIFTY50` / `ORUKAN` / `orukan_jpy`）。

#### 環境設定の例
- ローカル検証（疑似データのみで完結させたい場合）
  - `BACKTEST_ALLOW_FALLBACK=1`
  - `SP500_ALLOW_SYNTHETIC_FALLBACK=1`
  - `TOPIX_ALLOW_SYNTHETIC_FALLBACK=1`
  - `NIKKEI_ALLOW_SYNTHETIC_FALLBACK=1`
  - `NIFTY50_ALLOW_SYNTHETIC_FALLBACK=1`
  - 実データ用キーは未設定でも 200 が返り、決定的な疑似系列で計算されます。
- 本番想定（実データ優先・失敗時フォールバック）
  - `SP500_SYMBOL=VOO`（または好みの S&P500 連動銘柄）
  - `TOPIX_SYMBOL=1306.T`（任意の TOPIX 連動銘柄）
  - `NIKKEI_SYMBOL=^N225`
  - `NIFTY50_SYMBOL=^NSEI`
  - `ORUKAN_SYMBOL=ACWI`（オルカンは ACWI の値動きを利用）
  - `ORUKAN_JPY_SYMBOL=ACWI` / `ORUKAN_JPY_FX_SYMBOL=JPY=X`（オルカン円建ては ACWI をドル円で換算）
  - `FRED_API_KEY=<your_key>`（マクロ指標が実データになります）
  - `BACKTEST_ALLOW_FALLBACK=1` / `SP500_ALLOW_SYNTHETIC_FALLBACK=1` / `TOPIX_ALLOW_SYNTHETIC_FALLBACK=1` / `NIKKEI_ALLOW_SYNTHETIC_FALLBACK=1` / `NIFTY50_ALLOW_SYNTHETIC_FALLBACK=1`（回線断時に疑似系列へ切替）
  - NAV API を使う場合は `SP500_NAV_API_BASE` / `TOPIX_NAV_API_BASE` / `NIKKEI_NAV_API_BASE` / `NIFTY50_NAV_API_BASE` を追加設定

バックエンド起動時には、マーケットサービスとバックテストの各フォールバック設定がログに出力されます（例: `[MARKET CONFIG] ...`, `[BACKTEST CONFIG] ...`）。外部データ経路が使われたかどうかも INFO ログで確認できます。

※ ユニットテスト実行: `python -m pytest backend/tests`

### 計算ロジックの入力/出力メモ
- ポジション計算は「円建て S&P500 連動投信」を前提にしており、平均取得単価と評価額・損益は円で返却します（為替は yfinance の USD/JPY 終値を使用）。
- `/api/sp500/evaluate` のレスポンスには価格系列 `price_series`（日付・終値・MA20/60/200）を含め、チャートの横軸に日付を表示できるようにしています。

## フロントエンドの起動
1. 依存関係をインストール
   ```bash
   cd frontend
   npm install
   ```
2. API ベース URL を指定（任意）
   - バックエンドが別ホストの場合は `.env` に `VITE_API_BASE=<http://backend-host:8000>` を設定します。
   - ローカル開発でバックエンドを 8000 番ポートで動かす場合、未設定でも Vite の `/api` プロキシ経由でアクセスできます。
3. 開発サーバーを起動
   ```bash
   npm run dev
   ```
4. ブラウザで表示
   - http://localhost:5173

### フロントエンドの UI メモ
- 重要なお知らせは、ヘッダー右側のアニメーションするシグナルライトで示しています。点滅している場合は通知エリアを開いて最新の案内を確認してください。

## リポジトリ構成
- `backend/`: FastAPI アプリとスコアロジック
- `frontend/`: React + Vite の SPA
