import {
  Container,
  Box,
  Typography,
  Switch,
  Stack,
  ToggleButtonGroup,
  ToggleButton,
  Paper,
} from '@mui/material'
import { useEffect, useMemo, useState } from 'react'
import LightModeIcon from '@mui/icons-material/LightMode'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import { PaletteMode } from '@mui/material'
import { Routes, Route, useLocation, useNavigate } from 'react-router-dom'
import DashboardPage from './components/DashboardPage'
import BacktestPage from './components/BacktestPage'
import { emitLanguageChanged, getInitialLanguage, getTranslations, type AppLanguage } from './i18n'

interface AppProps {
  mode: PaletteMode
  onToggleMode: () => void
}

const EN_TEXT_REPLACEMENTS: Record<string, string> = {
  '⚠ 本サービスは投資助言ではありません。表示されるスコアは参考情報であり、最終的な投資判断はご自身の責任で行ってください。':
    '⚠ This service is not investment advice. Scores are for reference only. Final investment decisions are your own responsibility.',
  '※ ページ更新や条件切り替え時、最新データの取得・計算のため表示が反映されるまで数秒かかる場合があります。':
    'Note: after refreshes or condition changes, it may take a few seconds for the latest data and calculations to appear.',
  '対象インデックス': 'Target index',
  '最終更新': 'Last updated',
  '更新中…': 'Updating…',
  '再取得中…': 'Retrying…',
  '最新データを取得': 'Refresh latest data',
  'ホールド': 'Hold',
  '時間軸別の評価（参考）': 'Time-horizon view (reference)',
  '総合スコアは「今どうすべきか」の結論です。': 'The total score is the practical “what now?” view.',
  'ここでは、その判断の背景を時間軸ごとの評価として確認できます。': 'Here you can review the background by time horizon.',
  '短期目線': 'Short term',
  '中期目線': 'Medium term',
  '長期目線': 'Long term',
  '短期目線の内訳': 'Short-term breakdown',
  '中期目線の内訳': 'Medium-term breakdown',
  '長期目線の内訳': 'Long-term breakdown',
  'テクニカル': 'Technical',
  'マクロ': 'Macro',
  'イベント補正': 'Event adjustment',
  'マクロ M': 'Macro M',
  '短期目線スコア:': 'Short-term score:',
  '中期目線スコア:': 'Medium-term score:',
  '長期目線スコア:': 'Long-term score:',
  '短期目線では、直近の値動きや過熱感、イベントの影響を重視します。': 'The short-term view focuses on recent price moves, overheating, and event risk.',
  '「今すぐ動くべきか」「一時的な調整が入りそうか」といった直近のリスクを確認する視点です。': 'It is useful for checking near-term risks such as whether action is needed now or a pullback may be near.',
  '短期的なノイズも多いため、ここでの判断はタイミング調整の意味合いが強くなります。': 'Because short-term noise is high, this view is mainly for timing adjustments.',
  '中期目線では、トレンドの持続性や環境の変化を重視します。': 'The medium-term view focuses on trend durability and changes in the market environment.',
  '短期のブレをならしながら、「流れとしてどうか？」を判断する視点です。': 'It smooths out short-term noise and asks whether the overall flow is still healthy.',
  'この視点は、売り・保有・様子見の判断の中心になります。': 'This view is the core reference for trim, hold, or wait decisions.',
  '長期目線では、過去の平均水準や構造的な割高・割安感を重視します。': 'The long-term view focuses on historical averages and structural overvaluation or undervaluation.',
  '「今は歴史的に見てどの位置か？」という俯瞰の視点です。': 'It gives a broader view of where the market stands historically.',
  'ここでの判断は、天井圏か、まだ余地があるかを確認する意味合いになります。': 'This helps judge whether the market may be near a top or still has room.',
  '表示モード': 'Display mode',
  '正規化': 'Normalized',
  '実価格': 'Actual price',
  '開始時点': 'Start point',
  '全期間': 'Full period',
  '1か月': '1 month',
  '3ヶ月前': '3 months ago',
  '6か月': '6 months',
  '1年': '1 year',
  '3年前': '3 years ago',
  '5年前': '5 years ago',
  '日付を指定': 'Custom date',
  '開始日を指定': 'Start date',
  '為替インサイト': 'FX insight',
  '1か月差': '1M difference',
  '重要イベント': 'Important events',
  'イベント補正': 'Event adjustment',
  '次の重要イベントまで': 'Next important event in',
  '本日': 'Today',
  'これからのイベント': 'Upcoming events',
  '注目': 'Watch',
  '推定': 'Estimated',
  '直近1か月で円建てがドル建てを': 'Over the past month, the JPY-based return is',
  '下回っています。円高（USD/JPY低下）方向の影響で、円建てリターンが抑えられています。': 'below the USD-based return. JPY strength is weighing on yen-based returns.',
  '上回っています。円安（USD/JPY上昇）方向の影響で、円建てリターンが押し上げられています。': 'above the USD-based return. JPY weakness is lifting yen-based returns.',
  '米10年債利回り過去10年レンジに対するパーセンタイル': 'US 10Y yield percentile vs 10-year range',
  'インフレ（CPI）過去10年レンジに対するパーセンタイル': 'CPI percentile vs 10-year range',
  'VIX過去10年レンジに対するパーセンタイル': 'VIX percentile vs 10-year range',
  '高め': 'High',
  '加速': 'Accelerating',
  '注意': 'Caution',
  '終値': 'Close',
  'マイポジ試算（任意）': 'My position simulation (optional)',
  'あなたのポジションで試算（任意）': 'Simulate with your position (optional)',
  'マイポジ試算': 'My position simulation',
  '閉じる': 'Close',
}

const translateRemainingDom = (language: AppLanguage) => {
  if (typeof document === 'undefined' || language !== 'en') return
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT)
  const nodes: Text[] = []
  while (walker.nextNode()) nodes.push(walker.currentNode as Text)
  nodes.forEach((node) => {
    const original = node.nodeValue ?? ''
    const trimmed = original.trim()
    if (!trimmed) return
    let translated = EN_TEXT_REPLACEMENTS[trimmed]
    if (!translated) {
      translated = trimmed
        .replace(/^最終更新: /, 'Last updated: ')
        .replace(/^イベント補正: /, 'Event adjustment: ')
        .replace(/^1か月差: /, '1M difference: ')
        .replace(/(|\s)*円建て/g, ' JPY-based')
    }
    if (translated && translated !== trimmed) {
      node.nodeValue = original.replace(trimmed, translated)
    }
  })
}

function App({ mode, onToggleMode }: AppProps) {
  const [displayMode, setDisplayMode] = useState<'pro' | 'simple'>(() => {
    if (typeof window === 'undefined') return 'simple'
    const stored = window.localStorage.getItem('displayMode')
    return stored === 'pro' || stored === 'simple' ? stored : 'simple'
  })
  const [language, setLanguage] = useState<AppLanguage>(() => getInitialLanguage())
  const location = useLocation()
  const navigate = useNavigate()
  const t = getTranslations(language)

  const currentTab = useMemo(() => {
    return location.pathname.startsWith('/backtest') ? 'backtest' : 'dashboard'
  }, [location.pathname])

  const handleDisplayMode = (_: any, next: 'pro' | 'simple') => {
    if (next) setDisplayMode(next)
  }

  const handleLanguage = (_: any, next: AppLanguage | null) => {
    if (next) setLanguage(next)
  }

  useEffect(() => {
    if (typeof window === 'undefined') return
    window.localStorage.setItem('displayMode', displayMode)
  }, [displayMode])

  useEffect(() => {
    if (typeof window === 'undefined') return
    emitLanguageChanged(language)
    document.documentElement.lang = language
  }, [language])

  useEffect(() => {
    if (typeof window === 'undefined' || language !== 'en') return
    translateRemainingDom(language)
    const observer = new MutationObserver(() => translateRemainingDom(language))
    observer.observe(document.body, { childList: true, subtree: true, characterData: true })
    return () => observer.disconnect()
  }, [language, location.pathname, displayMode])

  const handleTabChange = (_: any, next: 'dashboard' | 'backtest' | null) => {
    if (!next) return
    if (next === 'dashboard') navigate('/')
    if (next === 'backtest') navigate('/backtest')
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Box display="flex" justifyContent="space-between" alignItems="center" mb={3} flexWrap="wrap" gap={2}>
        <Box>
          <Typography variant="h4" fontWeight={700} color="primary.light">
            {t.app.title}
          </Typography>
          <Typography variant="subtitle1" color="text.secondary">
            {t.app.subtitle}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Paper variant="outlined" sx={{ p: 0.5, borderRadius: 2 }}>
            <ToggleButtonGroup value={currentTab} exclusive onChange={handleTabChange} size="small">
              <ToggleButton value="dashboard">{t.app.mainTab}</ToggleButton>
              <ToggleButton value="backtest">{t.app.backtestTab}</ToggleButton>
            </ToggleButtonGroup>
          </Paper>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="text.secondary">{t.app.languageLabel}</Typography>
            <ToggleButtonGroup value={language} exclusive size="small" onChange={handleLanguage}>
              <ToggleButton value="ja">{t.app.japanese}</ToggleButton>
              <ToggleButton value="en">{t.app.english}</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="text.secondary">{t.app.modeLabel}</Typography>
            <ToggleButtonGroup value={displayMode} exclusive size="small" onChange={handleDisplayMode}>
              <ToggleButton value="simple">{t.app.simpleMode}</ToggleButton>
              <ToggleButton value="pro">{t.app.proMode}</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Stack direction="row" spacing={1} alignItems="center">
            <LightModeIcon color={mode === 'light' ? 'primary' : 'disabled'} />
            <Switch checked={mode === 'dark'} onChange={onToggleMode} color="primary" />
            <DarkModeIcon color={mode === 'dark' ? 'primary' : 'disabled'} />
          </Stack>
        </Stack>
      </Box>
      <Routes>
        <Route path="/" element={<DashboardPage displayMode={displayMode} />} />
        <Route path="/backtest" element={<BacktestPage language={language} />} />
      </Routes>
    </Container>
  )
}

export default App
