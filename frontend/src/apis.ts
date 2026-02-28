import type { BacktestRequest, BacktestResult } from './types/apis'

/**
 * バックエンドのベースURL
 * - 通常: VITE_API_BASE（Render本番など）
 * - 未設定時: window.location.origin（ローカル動作用）
 */
const apiBase =
  import.meta.env.VITE_API_BASE ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

/**
 * バックテスト実行 API
 * POST /api/backtest
 */
export async function runBacktest(payload: BacktestRequest): Promise<BacktestResult> {
  const res = await fetch(`${apiBase}/api/backtest`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })

  if (!res.ok) {
    const text = await res.text()
    throw new Error(`Backtest failed: ${res.status} ${text}`)
  }

  return res.json()
}

/**
 * イベント1件分の型
 * backend の EventService / /api/events のレスポンスに対応
 */
export interface EventItem {
  name: string
  importance: number
  date: string // ISO形式 "2025-01-29"
  source?: 'manual' | 'heuristic' | string
  description?: string
  // 将来フィールド追加されても壊れないようにしておく
  [key: string]: unknown
}

/**
 * イベント取得 API
 * GET /api/events?date=YYYY-MM-DD
 *
 * 例:
 *  - fetchEvents('2025-01-29')
 *  - fetchEvents()  // 日付未指定の場合はバックエンド側で「今日」扱い
 */
export async function fetchEvents(dateIso?: string): Promise<EventItem[]> {
  const url = new URL(`${apiBase}/api/events`)

  if (dateIso) {
    // 念のため両方付ける（backend がどちらを採用しても動く）
    url.searchParams.set('date', dateIso)
    url.searchParams.set('date_str', dateIso)
  }

  const res = await fetch(url.toString(), {
    method: 'GET',
  })

  if (!res.ok) {
    const text = await res.text()
    console.error('Events API error:', res.status, text)
    throw new Error(`Failed to fetch events: ${res.status} ${text}`)
  }

  const json = await res.json()
  const rawEvents = Array.isArray(json?.events)
    ? json.events
    : Array.isArray(json)
      ? json
      : []

  const normalized = rawEvents
    .filter((ev: unknown): ev is Record<string, unknown> => !!ev && typeof ev === 'object')
    .map((ev: Record<string, unknown>) => ({
      name: typeof ev.name === 'string' ? ev.name : 'Unknown Event',
      importance: typeof ev.importance === 'number' ? ev.importance : 3,
      date: typeof ev.date === 'string' ? ev.date : String(json?.target ?? ''),
      source: typeof ev.source === 'string' ? ev.source : 'manual',
      description: typeof ev.description === 'string' ? ev.description : undefined,
    }))
    .filter((ev: EventItem) => ev.date.length > 0)

  return normalized
}
