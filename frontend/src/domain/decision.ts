export const DECISION_VALUES = ['TAKE_PROFIT', 'WAIT', 'HOLD_OR_BUY'] as const

export type Decision = (typeof DECISION_VALUES)[number]

const DECISION_THRESHOLDS = {
  TAKE_PROFIT: 60,
  WAIT: 40,
}

export function deriveDecision(totalScore?: number): Decision {
  if (totalScore === undefined || Number.isNaN(totalScore)) return 'WAIT'
  if (totalScore >= DECISION_THRESHOLDS.TAKE_PROFIT) return 'TAKE_PROFIT'
  if (totalScore >= DECISION_THRESHOLDS.WAIT) return 'WAIT'
  return 'HOLD_OR_BUY'
}
