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
import { useMemo, useState } from 'react'
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

function App({ mode, onToggleMode }: AppProps) {
  const [displayMode, setDisplayMode] = useState<'pro' | 'simple'>('pro')
  const location = useLocation()
  const navigate = useNavigate()

  const currentTab = useMemo(() => {
    return location.pathname.startsWith('/backtest') ? 'backtest' : 'dashboard'
  }, [location.pathname])

  const handleDisplayMode = (_: any, next: 'pro' | 'simple') => {
    if (next) setDisplayMode(next)
  }

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
            売り時くん
          </Typography>
          <Typography variant="subtitle1" color="text.secondary">
            テクニカル・マクロ・イベントの三軸で売り時スコアを可視化
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
              <ToggleButton value="dashboard">メイン画面</ToggleButton>
              <ToggleButton value="backtest">バックテスト画面</ToggleButton>
            </ToggleButtonGroup>
          </Paper>
          <Box display="flex" alignItems="center" gap={1}>
            <Typography variant="body2" color="text.secondary">
              表示モード
            </Typography>
            <ToggleButtonGroup value={displayMode} exclusive size="small" onChange={handleDisplayMode}>
              <ToggleButton value="pro">プロ向け</ToggleButton>
              <ToggleButton value="simple">かんたん</ToggleButton>
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
