import {
  Card,
  CardContent,
  Typography,
  Stack,
  Box,
  alpha,
  useTheme,
  Tooltip,
  Divider,
  Button,
  Alert,
  Chip,
  Skeleton,
} from '@mui/material'
import type { TooltipTexts } from '../tooltipTexts'
import { useAppLanguage, getTranslations } from '../i18n'

type EvalStatus = 'loading' | 'ready' | 'degraded' | 'error' | 'refreshing'

interface ScoreSummaryCardProps {
  scores?: {
    total: number | null
    label: string
  }
  zoneText?: string
  expanded?: boolean
  onShowDetails?: () => void
  tooltips: TooltipTexts
  status?: EvalStatus
  statusMessage?: string
  onRetry?: () => void
  isRetrying?: boolean
  overallScoreNoteTitle?: string
  overallScoreNoteLines?: string[]
}

const getLocalizedScoreZoneText = (score: number | undefined, t: ReturnType<typeof getTranslations>) => {
  if (score === undefined) return t.scoreZones.loading
  if (score >= 80) return t.scoreZones.sellLine
  if (score >= 75) return t.scoreZones.strong
  if (score >= 65) return t.scoreZones.push
  if (score >= 60) return t.scoreZones.caution
  if (score >= 40) return t.scoreZones.average
  if (score >= 20) return t.scoreZones.low
  return t.scoreZones.veryLow
}

function ScoreSummaryCard({
  scores,
  zoneText,
  expanded,
  onShowDetails,
  tooltips,
  status = 'ready',
  statusMessage,
  onRetry,
  isRetrying = false,
  overallScoreNoteTitle,
  overallScoreNoteLines,
}: ScoreSummaryCardProps) {
  const language = useAppLanguage()
  const t = getTranslations(language)
  const d = t.dashboard
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const gradientStart = isDark ? '#101726' : alpha(theme.palette.primary.light, 0.2)
  const gradientEnd = isDark ? '#0c1b34' : alpha(theme.palette.secondary.light, 0.16)
  const showConfirmed = status === 'ready' || status === 'refreshing'
  const totalScore = scores?.total
  const isTotalScoreFinite = typeof totalScore === 'number' && Number.isFinite(totalScore)
  const localizedZoneText = getLocalizedScoreZoneText(showConfirmed && isTotalScoreFinite ? totalScore : undefined, t)
  const zoneTextValue = language === 'en' ? localizedZoneText : zoneText ?? localizedZoneText
  const showDetailsToggle = Boolean(onShowDetails) && expanded !== undefined
  const noteTitle = overallScoreNoteTitle ?? d.scoreNoteTitle
  const noteLines = overallScoreNoteLines ?? [...d.scoreNoteLines]

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
          {status === 'degraded' && (
            <Alert
              severity="warning"
              action={
                onRetry ? (
                  <Button color="inherit" size="small" onClick={onRetry}>
                    {d.retry}
                  </Button>
                ) : undefined
              }
            >
              <Typography variant="subtitle2" component="div">
                {d.degradedTitle}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {statusMessage ?? d.degradedMessage}
              </Typography>
              {isRetrying && (
                <Typography variant="caption" color="text.secondary">
                  {d.retrying}
                </Typography>
              )}
            </Alert>
          )}
          {status === 'error' && (
            <Alert
              severity="error"
              action={
                onRetry ? (
                  <Button color="inherit" size="small" onClick={onRetry}>
                    {d.retry}
                  </Button>
                ) : undefined
              }
            >
              <Typography variant="subtitle2" component="div">
                {d.errorTitle}
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {statusMessage ?? d.errorMessage}
              </Typography>
            </Alert>
          )}

          <Box
            display="grid"
            gridTemplateColumns={{ xs: '1fr', md: 'minmax(0, 1fr) minmax(260px, 0.9fr)' }}
            gap={2}
            alignItems="start"
          >
            <Stack spacing={0.75}>
              <Tooltip title={tooltips.score.total} arrow>
                <Typography variant="overline" color="text.secondary" component="div">
                  {d.totalScore}
                </Typography>
              </Tooltip>
              <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                {status === 'loading' ? (
                  <Skeleton variant="text" width={120} height={44} />
                ) : (
                  <Typography variant="h3" color="primary.main" fontWeight={700}>
                    {showConfirmed && isTotalScoreFinite ? totalScore.toFixed(1) : 'N/A'}
                  </Typography>
                )}
                {status === 'refreshing' && <Chip size="small" color="info" label={d.refreshing} />}
              </Stack>
            </Stack>

            <Box
              sx={{
                borderRadius: 2,
                px: 1.5,
                py: 1.25,
                bgcolor: alpha(theme.palette.background.default, 0.28),
                border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
              }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ fontWeight: 700 }}>
                {noteTitle}
              </Typography>
              <Stack spacing={0.5} mt={0.75}>
                {noteLines.map((line, index) => (
                  <Typography key={`overall-score-note-${index}`} variant="caption" color="text.secondary">
                    {line}
                  </Typography>
                ))}
              </Stack>
            </Box>
          </Box>

          <Typography variant="overline" color="text.secondary" component="div">
            {d.exitCloseness}
          </Typography>
          <Tooltip title={tooltips.score.label} arrow>
            <Typography variant="subtitle1" color="text.secondary" component="div">
              {showConfirmed ? scores?.label ?? d.pending : status === 'degraded' ? d.unconfirmed : d.calculating}
            </Typography>
          </Tooltip>
          <Typography variant="body2" color="text.secondary">
            {status === 'loading' ? d.loading : zoneTextValue}
          </Typography>

          {showDetailsToggle && (
            <>
              <Divider />
              <Button variant="outlined" color="inherit" onClick={onShowDetails} sx={{ alignSelf: 'flex-start' }}>
                {expanded ? d.detailsClose : d.detailsOpen}
              </Button>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

export default ScoreSummaryCard
