import type { ScoreMaDays } from './maAvatarMap'

export type MaPersona = {
  label: string
  duration: string
  icon: string
  copyTitle: string
  copyBody: string
}

export const MA_ORDER: ScoreMaDays[] = [20, 60, 200]

export const MA_PERSONA: Record<ScoreMaDays, MaPersona> = {
  20: {
    label: '短期',
    duration: '2〜6週間',
    icon: '⏱',
    copyTitle: '短期視点（2〜6週）',
    copyBody: '今の動きに素早く反応します。短いサイクルの売却を検討するレンズです。',
  },
  60: {
    label: '中期',
    duration: '1〜3か月',
    icon: '📅',
    copyTitle: '中期視点（1〜3か月）',
    copyBody: '流れを見て判断します。バランスの取れた売却目安を示すレンズです。',
  },
  200: {
    label: '長期',
    duration: '3か月〜1年',
    icon: '🧭',
    copyTitle: '長期視点（3か月〜1年）',
    copyBody: '大局を重視します。ゆったりと利確タイミングを計るレンズです。',
  },
}
