import { Card, CardContent, Typography, LinearProgress, Stack, Box, alpha, useTheme, Tooltip } from '@mui/material'
import type { TooltipTexts } from '../tooltipTexts'
import { getScoreZoneText } from '../utils/alertState'

interface ScoreSummaryCardProps {
  scores?: {
    technical: number
    macro: number
    event_adjustment: number
    total: number
    label: string
  }
  technical?: { d: number; T_base: number; T_trend: number }
  macro?: { p_r: number; p_cpi: number; p_vix: number; M: number }
  tooltips: TooltipTexts
}

function ScoreSummaryCard({ scores, technical, macro, tooltips }: ScoreSummaryCardProps) {
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const gradientStart = isDark ? '#101726' : alpha(theme.palette.primary.light, 0.2)
  const gradientEnd = isDark ? '#0c1b34' : alpha(theme.palette.secondary.light, 0.16)
  const zoneText = getScoreZoneText(scores?.total)

  return (
    <Card
      sx={{
        height: '100%',
        background: `linear-gradient(135deg, ${gradientStart}, ${gradientEnd})`,
        border: isDark ? '1px solid rgba(255,255,255,0.04)' : `1px solid ${alpha(theme.palette.primary.main, 0.1)}`,
      }}
    >
      <CardContent>
        <Stack spacing={2}>
          <Tooltip title={tooltips.score.total} arrow>
            <Typography variant="overline" color="text.secondary" component="div">
              総合スコア
            </Typography>
          </Tooltip>
          <Typography variant="h3" color="primary.main" fontWeight={700}>
            {scores ? scores.total.toFixed(1) : '--'}
          </Typography>
          <Tooltip title={tooltips.score.label} arrow>
            <Typography variant="subtitle1" color="text.secondary" component="div">
              {scores?.label ?? '計算待ち'}
            </Typography>
          </Tooltip>
          <Typography variant="body2" color="text.secondary">
            {zoneText}
          </Typography>

          <Stack spacing={1}>
            <LabelBar label="テクニカル" tooltip={tooltips.score.technical} value={scores?.technical} color="primary" />
            <LabelBar label="マクロ" tooltip={tooltips.score.macro} value={scores?.macro} color="secondary" />
            <LabelBar label="イベント補正" tooltip={tooltips.score.event} value={scores?.event_adjustment} color="error" />
          </Stack>

          {technical && macro && (
            <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={1}>
              <DetailItem label="乖離率 d" tooltip={tooltips.score.d} value={`${technical.d}%`} />
              <DetailItem label="T_base" tooltip={tooltips.score.T_base} value={technical.T_base} />
              <DetailItem label="T_trend" tooltip={tooltips.score.T_trend} value={technical.T_trend} />
              <DetailItem label="マクロ M" tooltip={tooltips.score.macroM} value={macro.M} />
            </Box>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

function LabelBar({
  label,
  tooltip,
  value,
  color,
}: {
  label: string
  tooltip: string
  value?: number
  color: 'primary' | 'secondary' | 'error'
}) {
  return (
    <Box>
      <Box display="flex" justifyContent="space-between" mb={0.5}>
        <Tooltip title={tooltip} arrow>
          <Typography variant="body2" color="text.secondary" component="div">
            {label}
          </Typography>
        </Tooltip>
        <Typography variant="body2" color={`${color}.light`}>
          {value !== undefined ? value.toFixed(1) : '--'}
        </Typography>
      </Box>
      <LinearProgress variant="determinate" value={value ? Math.min(Math.max(value, 0), 100) : 0} color={color} />
    </Box>
  )
}

function DetailItem({ label, tooltip, value }: { label: string; tooltip: string; value: number | string }) {
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  return (
    <Box
      bgcolor={
        isDark
          ? 'rgba(255,255,255,0.04)'
          : alpha(theme.palette.text.primary, 0.04)
      }
      p={1}
      borderRadius={1}
    >
      <Tooltip title={tooltip} arrow>
        <Typography variant="caption" color="text.secondary" component="div">
          {label}
        </Typography>
      </Tooltip>
      <Typography variant="body1">{value}</Typography>
    </Box>
  )
}

export default ScoreSummaryCard
