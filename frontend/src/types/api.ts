import type { IndexType } from './index'

export interface EvaluateRequest {
  total_quantity: number
  avg_cost: number
  index_type: IndexType
  score_ma: number
}

export interface EconomicEvent {
  name: string
  importance: number
  date: string
  source?: string
}

export interface PricePoint {
  date: string
  close: number
  ma20: number | null
  ma60: number | null
  ma200: number | null
}

export interface EvaluateResponse {
  current_price: number
  market_value: number
  unrealized_pnl: number
  scores: {
    technical: number
    macro: number
    event_adjustment: number
    total: number
    label: string
  }
  technical_details: {
    d: number
    T_base: number
    T_trend: number
  }
  macro_details: {
    p_r: number
    p_cpi: number
    p_vix: number
    M: number
  }
  event_details: {
    E_adj: number
    R_max: number
    effective_event: EconomicEvent | null
    events?: EconomicEvent[]
  }
  price_series: PricePoint[]
}

export interface SyntheticNavResponse {
  asOf: string
  priceUsd: number
  usdJpy: number
  navJpy: number
  source: string
}

export interface FundNavResponse {
  asOf: string
  navJpy: number
  source: string
}
