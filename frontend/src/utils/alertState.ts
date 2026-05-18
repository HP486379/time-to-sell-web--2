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
    title: '一括投資では売り検討ラインです',
    message: 'スコアが80以上です。一括投資では利益確定を具体的に検討できる水準です。',
    color: '#DCF2E3',
    icon: '🟢',
    face: '😎',
    reaction: '勢いに乗っている今のうちに、利確の計画を立てましょう。',
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

  if (score !== undefined && score >= 75 && score < 80) {
    return {
      decision: 'WAIT',
      title: '強めの警戒水準です',
      message: 'スコアが75以上です。まだ機械的な売り判断ではありませんが、過熱感は強まっています。',
      color: '#FFF1D6',
      icon: '🟠',
      face: '⚠️',
      reaction: '強めの警戒ゾーン。売却候補や利確ラインを先に決めておきましょう。',
    }
  }

  if (score !== undefined && score >= 65 && score < 75) {
    return {
      decision: 'WAIT',
      title: '通知対象の過熱水準です',
      message: 'スコアが65以上です。積立では新規積立分の一時待機を検討できる水準です。',
      color: '#E6F4FF',
      icon: '🔔',
      face: '🔔',
      reaction: '過熱を検知。焦って売るより、次の新規積立分を待機させる判断が現実的です。',
    }
  }

  if (score !== undefined && score >= 60 && score < 65) {
    return {
      decision: 'WAIT',
      title: '注意水準です',
      message: 'スコアが60以上です。アプリ内で注意して見る水準ですが、通知や売買判断にはまだ早めです。',
      color: '#EAF6FF',
      icon: 'ℹ️',
      face: '👀',
      reaction: '注意ゾーン入り。ここではまだ慌てず、65以上への上昇を確認しましょう。',
    }
  }

  return {
    decision,
    ...ALERT_DEFINITIONS[decision],
  }
}

export function getScoreZoneText(score?: number) {
  if (score === undefined) return 'スコアの計算中です。'
  if (score >= 80) return '現在のスコアは「一括投資版の売り検討ライン」です。'
  if (score >= 75) return '現在のスコアは「強めの警戒水準」です。'
  if (score >= 65) return '現在のスコアは「プッシュ通知対象の過熱水準」です。'
  if (score >= 60) return '現在のスコアは「アプリ内表示の注意水準」です。'
  if (score >= 40) return '現在のスコアは「平均的な水準」です。'
  if (score >= 20) return '現在のスコアは「やや低めの水準」です。'
  return '現在のスコアは「かなり低い水準」です。'
}
