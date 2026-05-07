import type { IndexType } from '../types/index'

export const toBacktestIndexType = (indexType: IndexType): string => {
  if (indexType === 'sp500_jpy') return 'SP500_JPY'
  if (indexType === 'NIKKEI') return 'NIKKEI225'
  if (indexType === 'ORUKAN') return 'ALLCOUNTRY'
  if (indexType === 'orukan_jpy') return 'ALLCOUNTRY_JPY'
  return indexType
}

export const NO_CLEAR_SELL_MESSAGE = '明確な売り時シグナルは出ていません。長期保有継続が優勢です。'
