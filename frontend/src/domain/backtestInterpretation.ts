import type { IndexType } from '../types/index'

export type BacktestViewStatus = {
  title: string
  judgement: string
  policy: string
  note: string
}

const NO_CLEAR_SELL_MESSAGES: Record<IndexType, BacktestViewStatus> = {
  SP500: {
    title: '明確な売り時シグナルは出ていません。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：過熱感が十分に高まっていない、またはSELL条件を満たしていません。',
  },
  SP500_JPY: {
    title: 'S&P500（円建て）は明確な売り時シグナルなしです。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：主力判定対象として監視中ですが、現時点はSELL条件未達です。',
  },
  ALLCOUNTRY: {
    title: 'オールカントリーは明確な売り時シグナルが出ていません。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：分散を保った長期保有継続が優勢です',
    note: '補足：過熱感またはSELLゲートの条件が十分ではありません。',
  },
  ALLCOUNTRY_JPY: {
    title: 'オールカントリー（円建て）は売り急ぐ局面ではありません。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：主力判定対象として評価中ですが、SELL条件は未充足です。',
  },
  TOPIX: {
    title: 'TOPIXは現時点で明確な売り時シグナルなしです。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：履歴・過熱条件の観点で、現時点はSELL条件を満たしていません。',
  },
  NIKKEI225: {
    title: '日経225は明確なSELLシグナル未発生です。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：過熱感が十分でない、またはSELL条件未達のため様子見です。',
  },
  NIFTY50: {
    title: 'NIFTY50は明確な売り時シグナルが出ていません。',
    judgement: '現在の判定：売り時ではありません',
    policy: '方針：長期保有継続が優勢です',
    note: '補足：SELL条件を満たすほどの過熱局面には到達していません。',
  },
}

export const getBacktestViewStatus = (indexType: IndexType, tradeCount: number | null | undefined): BacktestViewStatus | null => {
  if (typeof tradeCount !== 'number' || tradeCount > 0) return null
  return NO_CLEAR_SELL_MESSAGES[indexType]
}
