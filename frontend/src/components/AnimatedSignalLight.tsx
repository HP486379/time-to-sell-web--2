import { alpha, Box } from '@mui/material'
import { keyframes, styled } from '@mui/material/styles'
import type { Decision } from '../domain/decision'

interface AnimatedSignalLightProps {
  decision: Decision
}

const pulse = keyframes`
  0% {
    opacity: 0.4;
    box-shadow: 0 0 0 rgba(0, 0, 0, 0);
  }
  50% {
    opacity: 1;
    box-shadow: 0 0 8px rgba(0, 0, 0, 0.15);
  }
  100% {
    opacity: 0.4;
    box-shadow: 0 0 0 rgba(0, 0, 0, 0);
  }
`

const SignalHousing = styled(Box)(({ theme }) => ({
  display: 'inline-flex',
  alignItems: 'center',
  gap: 14,
  padding: '10px 16px',
  borderRadius: 18,
  justifyContent: 'center',
  background:
    theme.palette.mode === 'dark'
      ? 'linear-gradient(135deg, #1f2530 0%, #151b24 100%)'
      : 'linear-gradient(135deg, #f1f4f8 0%, #e7ecf3 100%)',
  border:
    theme.palette.mode === 'dark'
      ? '1px solid rgba(255, 255, 255, 0.08)'
      : '1px solid rgba(0, 0, 0, 0.08)',
  boxShadow:
    theme.palette.mode === 'dark'
      ? '0 14px 38px rgba(0, 0, 0, 0.45), inset 0 1px 0 rgba(255,255,255,0.04)'
      : '0 16px 46px rgba(0, 0, 0, 0.16), inset 0 1px 0 rgba(255,255,255,0.28)',
  minWidth: 176,
}))

const SignalBody = styled(Box)({
  display: 'flex',
  alignItems: 'center',
  gap: 14,
})

interface LightProps {
  bg: string
  active?: boolean
}

const Light = styled(Box, {
  shouldForwardProp: (prop) => prop !== 'bg' && prop !== 'active',
})<LightProps>(({ bg, active, theme }) => ({
  width: 36,
  height: 36,
  borderRadius: 9999,
  opacity: active ? 1 : 0.68,
  background: bg,
  boxShadow: [
    `inset 0 0 0 2px ${alpha('#ffffff', theme.palette.mode === 'dark' ? 0.16 : 0.4)}`,
    theme.palette.mode === 'dark'
      ? '0 6px 12px rgba(0, 0, 0, 0.45)'
      : '0 8px 16px rgba(0, 0, 0, 0.2)',
    theme.palette.mode === 'dark'
      ? '0 0 0 1px rgba(255, 255, 255, 0.06)'
      : '0 0 0 1px rgba(0, 0, 0, 0.12)',
    theme.palette.mode === 'dark'
      ? '0 0 0 3px rgba(0, 0, 0, 0.46)'
      : '0 0 0 3px rgba(255, 255, 255, 0.9)',
  ].join(', '),
  animation: active ? `${pulse} 1.2s ease-in-out infinite` : 'none',
}))

function getLabel(decision: Decision) {
  if (decision === 'TAKE_PROFIT') return '利確シグナル'
  if (decision === 'HOLD_OR_BUY') return '保有シグナル'
  return '様子見シグナル'
}

export const AnimatedSignalLight = ({ decision }: AnimatedSignalLightProps) => (
  <Box aria-label={getLabel(decision)} sx={{ flexShrink: 0 }}>
    <SignalHousing>
      <SignalBody>
        <Light bg="#ff4f4f" active={decision === 'HOLD_OR_BUY'} className="light light-red" />
        <Light bg="#f4c542" active={decision === 'WAIT'} className="light light-yellow" />
        <Light bg="#2ecc71" active={decision === 'TAKE_PROFIT'} className="light light-green" />
      </SignalBody>
    </SignalHousing>
  </Box>
)

