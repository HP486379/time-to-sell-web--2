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

interface AppProps {
  mode: PaletteMode
  onToggleMode: () => void
}

type AppLanguage = 'ja' | 'en'

function App({ mode, onToggleMode }: AppProps) {
  const [displayMode, setDisplayMode] = useState<'pro' | 'simple'>(() => {
    if (typeof window === 'undefined') return 'simple'
    const stored = window.localStorage.getItem('displayMode')
    return stored === 'pro' || stored === 'simple' ? stored : 'simple'
  })
  const [language, setLanguage] = useState<AppLanguage>(() => {
    if (typeof window === 'undefined') return 'ja'
    return window.localStorage.getItem('appLanguage') === 'en' ? 'en' : 'ja'
  })
  const location = useLocation()
  const navigate = useNavigate()
  const isEnglish = language === 'en'

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
    window.localStorage.setItem('appLanguage', language)
    document.documentElement.lang = language
  }, [language])

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
            {isEnglish ? 'Uritoki-kun' : '売り時くん'}
          </Typography>
          <Typography variant="subtitle1" color="text.secondary">
            {isEnglish
              ? 'A market overheat score for long-term investors: trim, rebalance, or pause DCA.'
              : 'テクニカル・マクロ・イベントの三軸で売り時スコアを可視化'}
          </Typography>
        </Box>
        <Stack direction="row" spacing={2} alignItems="center" flexWrap="wrap">
          <Paper variant="outlined" sx={{ p: 0.5, borderRadius: 2 }}>
            <ToggleButtonGroup
              value={currentTab}
              exclusive
              onChange={handleTabChange}
              size="small"
            >
              <ToggleButton value="dashboard">{isEnglish ? 'Main' : 'メイン画面'}</ToggleButton>
              <ToggleButton value="backtest">{isEnglish ? 'Backtest' : 'バックテスト画面'}</ToggleButton>
            </ToggleButtonGroup>
          </Paper>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="text.secondary">
              {isEnglish ? 'Language' : '言語'}
            </Typography>
            <ToggleButtonGroup value={language} exclusive size="small" onChange={handleLanguage}>
              <ToggleButton value="ja">日本語</ToggleButton>
              <ToggleButton value="en">English</ToggleButton>
            </ToggleButtonGroup>
          </Box>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="text.secondary">
              {isEnglish ? 'Mode' : '表示モード'}
            </Typography>
            <ToggleButtonGroup value={displayMode} exclusive size="small" onChange={handleDisplayMode}>
              <ToggleButton value="simple">{isEnglish ? 'Simple' : 'かんたん'}</ToggleButton>
              <ToggleButton value="pro">{isEnglish ? 'Pro' : 'プロ向け'}</ToggleButton>
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
        <Route path="/backtest" element={<BacktestPage />} />
      </Routes>
    </Container>
  )
}

export default App
