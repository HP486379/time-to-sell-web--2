import type { IndexType } from './index'

export interface BacktestRequest {
  start_date: string // "YYYY-MM-DD"
  end_date: string // "YYYY-MM-DD"
  initial_cash: number
  sell_threshold: number
  buy_threshold: number
  index_type: IndexType | string
  score_ma: number
}

export interface AccumulationBacktestRequest extends BacktestRequest {
  monthly_amount: number
  profit_take_pct: number
}

export interface BacktestSummary {
  final_equity: number
  hold_equity: number
  total_return: number
  max_drawdown: number
  trade_count: number
  hold_return?: number
  total_contributed?: number
  monthly_amount?: number
  profit_take_pct?: number
  profit_take_count?: number
  reinvest_count?: number
  contribution_count?: number
  waiting_cash?: number
}

export interface BacktestPoint {
  date: string
  close: number
  ma20?: number | null
  ma60?: number | null
  ma200?: number | null
}

export interface PortfolioPoint {
  date: string
  value: number
}

export interface BacktestResult {
  summary: BacktestSummary
  equity_curve: BacktestPoint[]
  portfolio_history?: PortfolioPoint[]
  buy_hold_history?: PortfolioPoint[]
  diagnostics?: Record<string, unknown>
}
