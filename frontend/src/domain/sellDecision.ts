import { type Decision } from './decision'

export function decideSellAction(totalScore?: number): Decision {
  if (totalScore === undefined || Number.isNaN(totalScore)) return 'HOLD_OR_BUY'
  if (totalScore >= 80) return 'TAKE_PROFIT'
  if (totalScore >= 60) return 'TAKE_PROFIT'
  if (totalScore >= 40) return 'WAIT'
  return 'HOLD_OR_BUY'
}
