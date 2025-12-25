import type { BacktestRequest, BacktestResult } from './types/apis'

const API_BASE = '/api'

export async function runBacktest(payload: BacktestRequest): Promise<BacktestResult> {
  const res = await fetch(`${API_BASE}/backtest`, {
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
