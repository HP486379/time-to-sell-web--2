import { deriveDecision, type Decision } from '../domain/decision'

export interface AlertState {
  decision: Decision
  title: string
  message: string
  reaction: string
  color: string
  icon: string
  face: string
}

const ALERT_DEFINITIONS: Record<Decision, Omit<AlertState, 'decision'>> = {
  TAKE_PROFIT: {
    title: '利確してOKな水準です',
    message: '株価は長期平均より上振れています。利益確定を積極的に検討できるゾーンです。',
    color: '#E4F6E8',
    icon: '🟢',
    face: '😄',
    reaction: 'いまが利確チャンス。どこで収穫するか作戦会議しましょう。',
  },
  WAIT: {
    title: '今は様子見で大丈夫です',
    message: '株価と環境は平均的。慌てず動向を見守るフェーズです。',
    color: '#FFF7E0',
    icon: '🟡',
    face: '( ˘ω˘ )',
    reaction: '穏やかなレンジ。タイミングを待ちましょう。',
  },
  HOLD_OR_BUY: {
    title: 'まだ売らずに保有寄りです',
    message: '株価は割安寄り。中長期ではホールドや買い増しで育てる局面です。',
    color: '#F7E6E6',
    icon: '🔴',
    face: '😌',
    reaction: '熟成中のゾーン。じっくり寝かせて育てましょう。',
  },
}

export function getAlertState(score?: number): AlertState {
  const decision = deriveDecision(score)

  const aggressiveTakeProfit =
    decision === 'TAKE_PROFIT' && score !== undefined && score >= 80

  if (aggressiveTakeProfit) {
    return {
      decision,
      title: '利確を強く推奨します',
      message: 'スコアが高水準です。利益確定を強く検討してください。',
      color: '#DCF2E3',
      icon: '🟢',
      face: '😎',
      reaction: '勢いに乗っている今のうちに、利確の計画を立てましょう。',
    }
  }

  return {
    decision,
    ...ALERT_DEFINITIONS[decision],
  }
}

export function getScoreZoneText(score?: number) {
  if (score === undefined) return 'スコアの計算中です。'
  if (score >= 80) return '現在のスコアは「かなり高い水準」です。'
  if (score >= 60) return '現在のスコアは「やや高めの水準」です。'
  if (score >= 40) return '現在のスコアは「平均的な水準」です。'
  if (score >= 20) return '現在のスコアは「やや低めの水準」です。'
  return '現在のスコアは「かなり低い水準」です。'
}
