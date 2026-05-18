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
