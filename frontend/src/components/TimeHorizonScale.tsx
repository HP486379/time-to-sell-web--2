import { alpha, useTheme } from '@mui/material/styles'
import { Box, Stack, Typography } from '@mui/material'
import { MA_ORDER, MA_PERSONA } from '../constants/maPersona'
import type { ScoreMaDays } from '../constants/maAvatarMap'

interface Props {
  active: ScoreMaDays
}

export function TimeHorizonScale({ active }: Props) {
  const theme = useTheme()
  const activeIndex = MA_ORDER.indexOf(active)
  const trackColor = alpha(theme.palette.text.primary, theme.palette.mode === 'dark' ? 0.25 : 0.12)
  const activeColor = theme.palette.mode === 'dark' ? theme.palette.success.light : theme.palette.success.main
  const textSubtle = alpha(theme.palette.text.primary, theme.palette.mode === 'dark' ? 0.72 : 0.65)
  const accentGlow = theme.palette.mode === 'dark' ? '0 0 0 8px rgba(124, 252, 190, 0.12)' : '0 0 0 8px rgba(72, 187, 120, 0.18)'
  const progress = (activeIndex / (MA_ORDER.length - 1)) * 100

  return (
    <Stack spacing={0.75} sx={{ width: '100%' }}>
      <Typography variant="overline" color={textSubtle} sx={{ letterSpacing: 0.4 }}>
        時間軸のレンズ
      </Typography>
      <Box position="relative" height={20}>
        <Box
          sx={{
            position: 'absolute',
            inset: '50% 8px auto',
            height: 6,
            transform: 'translateY(-50%)',
            backgroundColor: trackColor,
            borderRadius: 999,
          }}
        />
        <Box
          sx={{
            position: 'absolute',
            left: 8,
            top: '50%',
            height: 6,
            width: `clamp(12px, ${progress}%, 100%)`,
            transform: 'translateY(-50%)',
            background: `linear-gradient(90deg, ${activeColor}, ${theme.palette.primary.main})`,
            borderRadius: 999,
            transition: 'width 0.35s ease',
          }}
        />
        {MA_ORDER.map((ma, idx) => {
          const isActive = ma === active
          const left = `${(idx / (MA_ORDER.length - 1)) * 100}%`
          return (
            <Box
              key={ma}
              sx={{
                position: 'absolute',
                top: '50%',
                left,
                transform: 'translate(-50%, -50%)',
                width: 16,
                height: 16,
                borderRadius: '50%',
                backgroundColor: isActive ? activeColor : theme.palette.background.paper,
                border: `2px solid ${isActive ? activeColor : trackColor}`,
                boxShadow: isActive ? accentGlow : undefined,
                transition: 'all 0.25s ease',
              }}
            />
          )
        })}
      </Box>
      <Box display="flex" justifyContent="space-between" alignItems="center">
        {MA_ORDER.map((ma) => {
          const persona = MA_PERSONA[ma]
          const isActive = ma === active
          return (
            <Stack key={ma} spacing={0.25} alignItems="center" minWidth={0}>
              <Typography
                variant="body2"
                sx={{
                  fontWeight: 700,
                  color: isActive ? theme.palette.text.primary : textSubtle,
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.35,
                  whiteSpace: 'nowrap',
                }}
              >
                <span aria-hidden>{persona.icon}</span>
                {persona.label}
              </Typography>
              <Typography
                variant="caption"
                color={textSubtle}
                sx={{ whiteSpace: 'nowrap', fontSize: '0.72rem' }}
              >
                {persona.duration}
              </Typography>
            </Stack>
          )
        })}
      </Box>
    </Stack>
  )
}

export default TimeHorizonScale
