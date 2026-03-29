import type { IndexType } from './index'

export interface BacktestRequest {
  start_date: string // "YYYY-MM-DD"
  end_date: string // "YYYY-MM-DD"
  initial_cash: number
  sell_threshold: number
  buy_threshold: number
  index_type: IndexType
  score_ma: number
}

export interface BacktestSummary {
  final_equity: number
  hold_equity: number
  total_return: number
  max_drawdown: number
  trade_count: number
}

export interface BacktestPoint {
  date: string
  close: number
  ma20?: number | null
  ma60?: number | null
  ma200?: number | null
}

export interface BacktestResult {
  summary: BacktestSummary
  equity_curve: BacktestPoint[]
}
