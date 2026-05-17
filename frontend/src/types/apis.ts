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
  deferred_contribution_count?: number
  deferred_contribution_amount?: number
  overheat_signal_count?: number
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

export interface AccumulationScoreDiagnostics {
  first_score_date?: string | null
  first_score?: number | null
  min_score?: number | null
  max_score?: number | null
  days_score_above_sell_threshold?: number
  days_score_above_near_sell_threshold?: number
  near_sell_threshold?: number
  days_score_below_buy_threshold?: number
}

export interface AccumulationDiagnosticDate {
  date: string
  score?: number | null
  close?: number
  reason?: string
  signal_date?: string | null
}

export interface AccumulationDiagnostics {
  sell_candidate_count?: number
  near_sell_candidate_count?: number
  buy_candidate_count?: number
  blocked_by_cooldown_count?: number
  no_position_sell_candidate_count?: number
  overheat_signal_count?: number
  pending_overheat_signal?: boolean
  pending_overheat_signal_date?: string | null
  deferred_contribution_count?: number
  deferred_contribution_amount?: number
  top_score_dates?: AccumulationDiagnosticDate[]
  sell_candidate_dates?: AccumulationDiagnosticDate[]
  near_sell_candidate_dates?: AccumulationDiagnosticDate[]
  buy_candidate_dates?: AccumulationDiagnosticDate[]
  deferred_after_signal_dates?: AccumulationDiagnosticDate[]
  blocked_sell_dates?: AccumulationDiagnosticDate[]
  no_trade_reason?: string | null
}

export interface BacktestDiagnostics {
  result_source?: string
  backtest_type?: string
  index_type?: string
  start_date?: string
  end_date?: string
  score_ma?: number
  sell_threshold?: number
  buy_threshold?: number
  sell_policy?: string
  index_specific_sell_adjustment_applied?: boolean
  index_specific_sell_adjustment_note?: string
  score_samples?: AccumulationScoreDiagnostics
  accumulation_diagnostics?: AccumulationDiagnostics
  [key: string]: unknown
}

export interface BacktestResult {
  summary: BacktestSummary
  equity_curve: BacktestPoint[]
  portfolio_history?: PortfolioPoint[]
  buy_hold_history?: PortfolioPoint[]
  diagnostics?: BacktestDiagnostics
}
