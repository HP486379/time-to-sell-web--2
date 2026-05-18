import { useEffect, useState } from 'react'

export type AppLanguage = 'ja' | 'en'

export const DEFAULT_LANGUAGE: AppLanguage = 'ja'
export const APP_LANGUAGE_EVENT = 'appLanguageChanged'

export const translations = {
  ja: {
    app: {
      title: '売り時くん', subtitle: 'テクニカル・マクロ・イベントの三軸で売り時スコアを可視化', mainTab: 'メイン画面', backtestTab: 'バックテスト画面', languageLabel: '言語', japanese: '日本語', english: 'English', modeLabel: '表示モード', simpleMode: 'かんたん', proMode: 'プロ向け',
    },
    positioning: {
      notAdvice: '本サービスは投資助言ではありません。表示されるスコアは参考情報であり、最終的な投資判断はご自身の責任で行ってください。',
      delayNotice: 'ページ更新や条件切り替え時、最新データの取得・計算のため表示が反映されるまで数秒かかる場合があります。',
    },
    concept: { short: '高値圏での一部利確・リバランス・新規積立の一時待機を考えるための過熱スコア' },
    dashboard: {
      retry: '再取得', degradedTitle: '⚠ 一部データ取得中', degradedMessage: '価格履歴の取得が未完了のため、現在のスコアは参考値です。', retrying: '再試行中…', errorTitle: '❌ データ取得に失敗しました', errorMessage: '時間をおいて再取得してください。', refreshing: '更新中…', loading: '⏳ 計算中…',
      simpleAlert: 'シンプル・アラート', todayPoints: '今日のポイント', uncertainTitle: '未確定データを確認中', uncertainReaction: 'データが揃い次第、確定スコアを表示します。', uncertainScore: '現在のスコアは未確定です。', waitLoading: '計算完了までしばらくお待ちください。', detailsOpen: 'くわしく見る ≫', detailsClose: '閉じる',
      totalScore: '総合スコア', scoreNoteTitle: '総合スコア（統合判断）とは', scoreNoteLines: ['テクニカル・マクロ・イベント要因を統合した「今どうすべきか」の結論です。', '時間軸別の評価（短期/中期/長期）とは別指標のため、一致しない場合があります。'], exitCloseness: '出口接近度', pending: '計算待ち', unconfirmed: '未確定', calculating: '計算中', dataFailed: 'データ取得失敗',
      avatarTitle: '売り時くん', avatarCaption: 'スコアに応じて表示が変わります',
      alertTitles: { takeProfit: '一括投資では売り検討ラインです', strong: '強めの警戒水準です', push: '通知対象の過熱水準です', caution: '注意水準です', wait: '今は様子見で大丈夫です', hold: 'まだ売らずに保有寄りです' },
      alertMessages: { takeProfit: 'スコアが80以上です。一括投資では利益確定を具体的に検討できる水準です。', strong: 'スコアが75以上です。まだ機械的な利確判断ではありませんが、過熱感は強まっています。', push: 'スコアが65以上です。積立では新規積立分の一時待機を検討できる水準です。', caution: 'スコアが60以上です。アプリ内で注意して見る水準ですが、通知や売買判断にはまだ早めです。', wait: '株価と環境は平均的。慌てず動向を見守るフェーズです。', hold: '株価は割安寄り。中長期ではホールドや買い増しで育てる局面です。' },
      alertReactions: { takeProfit: '勢いに乗っている今のうちに、利確の計画を立てましょう。', strong: '強めの警戒ゾーン。候補や利確ラインを先に決めておきましょう。', push: '過熱を検知。次の新規積立分を待機させる判断が現実的です。', caution: '注意ゾーン入り。ここではまだ慌てず、65以上への上昇を確認しましょう。', wait: '穏やかなレンジ。タイミングを待ちましょう。', hold: '熟成中のゾーン。じっくり寝かせて育てましょう。' },
    },
    scoreZones: {
      loading: 'スコアの計算中です。', sellLine: '現在のスコアは「一括投資版の売り検討ライン」です。', strong: '現在のスコアは「強めの警戒水準」です。', push: '現在のスコアは「プッシュ通知対象の過熱水準」です。', caution: '現在のスコアは「アプリ内表示の注意水準」です。', average: '現在のスコアは「平均的な水準」です。', low: '現在のスコアは「やや低めの水準」です。', veryLow: '現在のスコアは「かなり低い水準」です。',
    },
    backtest: {
      title: 'バックテスト専用ページ', parameters: 'パラメータ', type: 'バックテスト種別', lumpSum: '一括投資', accumulation: '積立投資', startDate: '開始日', endDate: '終了日', initialCash: '初期資金', targetIndex: '対象インデックス', monthlyAmount: '毎月積立額', profitTakePct: '利確割合（%）', profitTakePctHelp: '積立待機方式では保有分売却なし。将来の利確方式用パラメータです。', sellThreshold: '売りしきい値', sellThresholdHelp: 'この値以上で次回積立を待機', buyThreshold: '買い戻ししきい値', buyThresholdHelp: 'この値未満で待機資金を再投入', scoreMa: 'スコア算出MA', ma20: '20日（短期・2〜6週間）', ma60: '60日（中期・1〜3か月）', ma200: '200日（長期・3か月〜1年）', run: 'バックテスト実行', running: '計算中...', result: '成績', finalAsset: '最終資産', buyAndHold: '単純ホールド', regularDcaHold: '通常積立ホールド', totalContributed: '累計積立額', waitingCash: '待機資金', deferredAndReinvest: '待機積立回数 / 再投入回数', deferredAmount: '待機した積立額', totalReturn: 'トータルリターン', regularDcaReturn: '通常積立リターン', maxDrawdown: '最大ドローダウン', tradeCount: '売買回数', emptyPrompt: 'パラメータを設定して「バックテスト実行」を押してください。', diagnostics: '積立診断', diagnosticsSub: '過熱時に新規積立を待機できたかを確認するための診断情報', maxScore: '最大スコア', aboveDays: '以上の日数', belowDays: '未満の日数', deferredCount: '待機積立回数', deferredContributionAmount: '待機積立額', noTradeReason: '待機なし理由', reasonNeverReached: 'スコアが売りしきい値に到達していません。', reasonAfterFinal: '最終積立後に過熱シグナルが出たため、次回積立待機まで進んでいません。', topScoreDates: 'スコア上位日', noScoreData: 'スコア診断データがありません。', assetChart: '資産推移', priceChart: '価格推移', strategyLine: '積立＋売り時くん', holdLine: '通常積立ホールド', closeLine: '終値',
    },
  },
  en: {
    app: {
      title: 'Uridoki-kun', subtitle: 'A market overheat score for long-term investors: trim, rebalance, or pause DCA.', mainTab: 'Main', backtestTab: 'Backtest', languageLabel: 'Language', japanese: '日本語', english: 'English', modeLabel: 'Mode', simpleMode: 'Simple', proMode: 'Pro',
    },
    positioning: {
      notAdvice: 'This service is not investment advice. Scores are for reference only, and final investment decisions are your own responsibility.', delayNotice: 'When refreshing or switching conditions, it may take a few seconds for the latest data and calculations to appear.',
    },
    concept: { short: 'An overheat score for deciding when to trim, rebalance, or pause new DCA contributions.' },
    dashboard: {
      retry: 'Retry', degradedTitle: '⚠ Some data is still loading', degradedMessage: 'Price history is not complete yet, so the current score is provisional.', retrying: 'Retrying…', errorTitle: '❌ Failed to load data', errorMessage: 'Please wait and try again.', refreshing: 'Updating…', loading: '⏳ Calculating…',
      simpleAlert: 'Simple alert', todayPoints: "Today's points", uncertainTitle: 'Checking provisional data', uncertainReaction: 'The final score will appear once enough data is available.', uncertainScore: 'The current score is not confirmed yet.', waitLoading: 'Please wait while the score is calculated.', detailsOpen: 'Show details ≫', detailsClose: 'Close',
      totalScore: 'Total score', scoreNoteTitle: 'What the total score means', scoreNoteLines: ['It combines technical, macro, and event factors into a practical “what now?” view.', 'It is separate from the short / medium / long-term reference scores, so they may not always match.'], exitCloseness: 'Exit proximity', pending: 'Pending', unconfirmed: 'Unconfirmed', calculating: 'Calculating', dataFailed: 'Data unavailable',
      avatarTitle: 'Uridoki-kun', avatarCaption: 'The character changes with the score.',
      alertTitles: { takeProfit: 'Lump-sum profit-taking review zone', strong: 'Strong warning zone', push: 'Push-alert overheat zone', caution: 'Caution zone', wait: 'No rush. Watch the market.', hold: 'Still closer to hold or accumulate' },
      alertMessages: { takeProfit: 'The score is 80 or higher. For lump-sum positions, this is a level where trimming or rebalancing can be reviewed.', strong: 'The score is 75 or higher. This is not a mechanical sell signal, but market overheating is becoming clearer.', push: 'The score is 65 or higher. For DCA investors, temporarily pausing new contributions can be considered.', caution: 'The score is 60 or higher. Watch it in the app, but it may still be early for notifications or action.', wait: 'Price and macro conditions look broadly normal. This is a wait-and-watch phase.', hold: 'The market does not look overheated. Long-term investors may simply stay the course.' },
      alertReactions: { takeProfit: 'Momentum is strong. Consider setting a profit-taking or rebalancing plan before emotions take over.', strong: 'Strong caution zone. Decide your trim, rebalance, or profit-taking line in advance.', push: 'Overheating detected. Pausing the next new contribution may be realistic.', caution: 'Caution zone. Stay calm and watch whether it moves above 65.', wait: 'A calm range. Let the setup come to you.', hold: 'Let the position mature. Patience matters here.' },
    },
    scoreZones: {
      loading: 'Calculating the score.', sellLine: 'This score is in the lump-sum profit-taking review zone.', strong: 'This score is in the strong warning zone.', push: 'This score is in the push-notification overheat zone.', caution: 'This score is in the in-app caution zone.', average: 'This score is in the average range.', low: 'This score is slightly low.', veryLow: 'This score is very low.',
    },
    backtest: {
      title: 'Backtest', parameters: 'Parameters', type: 'Backtest type', lumpSum: 'Lump sum', accumulation: 'DCA / Accumulation', startDate: 'Start date', endDate: 'End date', initialCash: 'Initial cash', targetIndex: 'Target index', monthlyAmount: 'Monthly contribution', profitTakePct: 'Trim ratio (%)', profitTakePctHelp: 'In DCA pause mode, existing holdings are not sold. This is reserved for future trim-style simulations.', sellThreshold: 'Overheat threshold', sellThresholdHelp: 'Pause the next contribution at or above this score', buyThreshold: 'Re-entry threshold', buyThresholdHelp: 'Reinvest waiting cash below this score', scoreMa: 'Score MA', ma20: '20 days (short term)', ma60: '60 days (medium term)', ma200: '200 days (long term)', run: 'Run backtest', running: 'Calculating...', result: 'Performance', finalAsset: 'Final asset', buyAndHold: 'Buy and hold', regularDcaHold: 'Regular DCA hold', totalContributed: 'Total contributed', waitingCash: 'Waiting cash', deferredAndReinvest: 'Deferred contributions / Reinvestments', deferredAmount: 'Deferred contribution amount', totalReturn: 'Total return', regularDcaReturn: 'Regular DCA return', maxDrawdown: 'Max drawdown', tradeCount: 'Trades', emptyPrompt: 'Set parameters and press “Run backtest.”', diagnostics: 'DCA diagnostics', diagnosticsSub: 'Checks whether new contributions were paused during overheated periods.', maxScore: 'Max score', aboveDays: '+ days', belowDays: 'below days', deferredCount: 'Deferred contributions', deferredContributionAmount: 'Deferred amount', noTradeReason: 'No-defer reason', reasonNeverReached: 'The score never reached the overheat threshold.', reasonAfterFinal: 'An overheat signal appeared after the final contribution, so it did not reach the next defer step.', topScoreDates: 'Top score dates', noScoreData: 'No score diagnostic data.', assetChart: 'Asset curve', priceChart: 'Price chart', strategyLine: 'DCA + Uridoki-kun', holdLine: 'Regular DCA hold', closeLine: 'Close',
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

export function emitLanguageChanged(language: AppLanguage) {
  if (typeof window === 'undefined') return
  window.localStorage.setItem('appLanguage', language)
  window.dispatchEvent(new CustomEvent<AppLanguage>(APP_LANGUAGE_EVENT, { detail: language }))
}

export function useAppLanguage(): AppLanguage {
  const [language, setLanguage] = useState<AppLanguage>(() => getInitialLanguage())

  useEffect(() => {
    const sync = () => setLanguage(getInitialLanguage())
    const onCustom = (event: Event) => {
      const detail = (event as CustomEvent<AppLanguage>).detail
      setLanguage(detail === 'en' ? 'en' : DEFAULT_LANGUAGE)
    }
    window.addEventListener('storage', sync)
    window.addEventListener(APP_LANGUAGE_EVENT, onCustom)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener(APP_LANGUAGE_EVENT, onCustom)
    }
  }, [])

  return language
}
