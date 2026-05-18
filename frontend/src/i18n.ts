export type AppLanguage = 'ja' | 'en'

export const DEFAULT_LANGUAGE: AppLanguage = 'ja'

export const translations = {
  ja: {
    app: {
      title: '売り時くん',
      subtitle: 'テクニカル・マクロ・イベントの三軸で売り時スコアを可視化',
      mainTab: 'メイン画面',
      backtestTab: 'バックテスト画面',
      languageLabel: '言語',
      japanese: '日本語',
      english: 'English',
      modeLabel: '表示モード',
      simpleMode: 'かんたん',
      proMode: 'プロ向け',
    },
    positioning: {
      notAdvice: '本サービスは投資助言ではありません。表示されるスコアは参考情報であり、最終的な投資判断はご自身の責任で行ってください。',
      delayNotice: 'ページ更新や条件切り替え時、最新データの取得・計算のため表示が反映されるまで数秒かかる場合があります。',
    },
    concept: {
      short: '高値圏での一部利確・リバランス・新規積立の一時待機を考えるための過熱スコア',
    },
  },
  en: {
    app: {
      title: 'Uridoki-kun',
      subtitle: 'A market overheat score for long-term investors: trim, rebalance, or pause DCA.',
      mainTab: 'Main',
      backtestTab: 'Backtest',
      languageLabel: 'Language',
      japanese: '日本語',
      english: 'English',
      modeLabel: 'Mode',
      simpleMode: 'Simple',
      proMode: 'Pro',
    },
    positioning: {
      notAdvice: 'This service is not investment advice. Scores are for reference only, and final investment decisions are your own responsibility.',
      delayNotice: 'When refreshing or switching conditions, it may take a few seconds for the latest data and calculations to appear.',
    },
    concept: {
      short: 'An overheat score for deciding when to trim, rebalance, or pause new DCA contributions.',
    },
  },
} as const

export function getInitialLanguage(): AppLanguage {
  if (typeof window === 'undefined') return DEFAULT_LANGUAGE
  return window.localStorage.getItem('appLanguage') === 'en' ? 'en' : DEFAULT_LANGUAGE
}

export function getTranslations(language: AppLanguage) {
  return translations[language]
}
