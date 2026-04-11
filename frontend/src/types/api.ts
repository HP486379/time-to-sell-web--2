import type { IndexType } from './index'

export interface EvaluateRequest {
  total_quantity: number
  avg_cost: number
  index_type: IndexType | string
  score_ma: number
  request_id?: string
}

export interface EconomicEvent {
  name: string
  importance: number
  date: string
  source?: string
  description?: string
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
  status: 'ready' | 'degraded' | 'error'
  reasons: string[]
  as_of: string
  request_id: string
  used_index_type: string
  source: string
  currency: string
  unit: string
  symbol: string
  scores: {
    technical: number | null
    macro: number | null
    event_adjustment: number | null
    total: number | null
    label: string
    period_total?: number | null
  }
  period_scores?: {
    short: number
    mid: number
    long: number
  }
  period_meta?: {
    short_window: number
    mid_window: number
    long_window: number
  }
  period_breakdowns?: {
    short: {
      scores: {
        technical: number
        macro: number
        event_adjustment: number
      }
      technical_details: {
        d: number
        T_base: number
        T_trend: number
        T_conv_adj?: number
        technical_score_raw?: number
      }
      macro_details: {
        macro_M?: number
        M?: number
        p_r?: number
        p_cpi?: number
        p_vix?: number
      }
    }
    mid: {
      scores: {
        technical: number
        macro: number
        event_adjustment: number
      }
      technical_details: {
        d: number
        T_base: number
        T_trend: number
        T_conv_adj?: number
        technical_score_raw?: number
      }
      macro_details: {
        macro_M?: number
        M?: number
        p_r?: number
        p_cpi?: number
        p_vix?: number
      }
    }
    long: {
      scores: {
        technical: number
        macro: number
        event_adjustment: number
      }
      technical_details: {
        d: number
        T_base: number
        T_trend: number
        T_conv_adj?: number
        technical_score_raw?: number
      }
      macro_details: {
        macro_M?: number
        M?: number
        p_r?: number
        p_cpi?: number
        p_vix?: number
      }
    }
  }
  technical_details: {
    d: number
    T_base: number
    T_trend: number
    T_conv_adj?: number
    convergence?: {
      side?: 'down_convergence' | 'up_convergence' | 'neutral'
    }
    multi_ma?: {
      dev10?: number | null
      dev50?: number | null
      dev200?: number | null
      level?: number
      label?: string
      text?: string
    }
  }
  macro_details: {
    p_r: number
    p_cpi: number
    p_vix: number
    M: number
  }
  event_adjustment_pt?: number
  event_count?: number
  event_details: {
    E_adj: number
    R_max: number
    effective_event: EconomicEvent | null
    events?: EconomicEvent[]
    warning?: string
  }
  price_series: PricePoint[]
  adopted_provider?: string | null
  debug?: {
    source?: string
    adopted_provider?: string | null
    provider_reject_reasons?: string[]
    resolved_symbol?: string
    index_mode?: string
  }
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
