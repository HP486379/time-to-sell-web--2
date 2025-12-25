import { Card, CardContent, Grid, Typography, Box, Chip, useTheme, alpha, Tooltip } from '@mui/material'
import type { TooltipTexts } from '../tooltipTexts'

interface Props {
  macroDetails?: {
    p_r: number
    p_cpi: number
    p_vix: number
    M: number
  }
  tooltips: TooltipTexts
}

const macroInfo = [
  { key: 'p_r', title: '米10年債利回り', color: '#f97316', desc: ['低め', 'ふつう', '高め'] },
  { key: 'p_cpi', title: 'インフレ (CPI)', color: '#a855f7', desc: ['鈍化', '中立', '加速'] },
  { key: 'p_vix', title: 'VIX', color: '#22d3ee', desc: ['穏やか', '注意', '警戒'] },
]

function MacroCards({ macroDetails, tooltips }: Props) {
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const cardBg = isDark
    ? 'linear-gradient(180deg,#0f172a,#0b1224)'
    : `linear-gradient(180deg, ${alpha(theme.palette.primary.light, 0.12)}, ${alpha(theme.palette.secondary.light, 0.08)})`

  return (
    <Grid container spacing={2}>
      {macroInfo.map((item) => {
        const percentile = macroDetails ? macroDetails[item.key as keyof typeof macroDetails] : undefined
        const labelIndex = percentile !== undefined ? Math.min(2, Math.floor(percentile * 3)) : 1
        return (
          <Grid item xs={12} sm={4} key={item.key}>
            <Card
              sx={{
                background: cardBg,
                border: isDark ? '1px solid rgba(255,255,255,0.05)' : `1px solid ${alpha(item.color, 0.25)}`,
              }}
            >
              <CardContent>
                <Tooltip
                  title={
                    item.key === 'p_r'
                      ? tooltips.macro.rate
                      : item.key === 'p_cpi'
                      ? tooltips.macro.cpi
                      : tooltips.macro.vix
                  }
                  arrow
                >
                  <Box>
                    <Typography variant="overline" color="text.secondary">
                      {item.title}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      過去10年レンジに対するパーセンタイル
                    </Typography>
                  </Box>
                </Tooltip>
                <Typography variant="h5" color={item.color} fontWeight={700}>
                  {Math.round((percentile ?? 0) * 100)} %tile
                </Typography>
                <Box mt={1}>
                  <Tooltip title={tooltips.macro.chip} arrow>
                    <Chip label={item.desc[labelIndex]} sx={{ color: item.color, borderColor: item.color }} variant="outlined" />
                  </Tooltip>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        )
      })}
    </Grid>
  )
}

export default MacroCards
