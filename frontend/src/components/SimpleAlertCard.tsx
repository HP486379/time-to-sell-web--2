import {
  Card,
  CardContent,
  Stack,
  Typography,
  Box,
  Button,
  useTheme,
  alpha,
  Tooltip,
  Divider,
  Alert,
  Chip,
  Skeleton,
} from '@mui/material'
import { darken } from '@mui/material/styles'
import ArrowForwardIcon from '@mui/icons-material/ArrowForward'
import type { TooltipTexts } from '../tooltipTexts'
import { getAlertState } from '../utils/alertState'
import { AnimatedSignalLight } from './AnimatedSignalLight'
import { getTranslations, useAppLanguage } from '../i18n'
import type { Decision } from '../domain/decision'

interface Props {
  scores?: {
    total: number
  }
  highlights?: { icon: string; text: string }[]
  zoneText?: string
  onShowDetails: () => void
  expanded: boolean
  tooltips: TooltipTexts
  status?: 'loading' | 'ready' | 'degraded' | 'error' | 'refreshing'
  statusMessage?: string
  onRetry?: () => void
  isRetrying?: boolean
}

const getLocalizedZoneText = (score: number | undefined, t: ReturnType<typeof getTranslations>) => {
  if (score === undefined) return t.scoreZones.loading
  if (score >= 80) return t.scoreZones.sellLine
  if (score >= 75) return t.scoreZones.strong
  if (score >= 65) return t.scoreZones.push
  if (score >= 60) return t.scoreZones.caution
  if (score >= 40) return t.scoreZones.average
  if (score >= 20) return t.scoreZones.low
  return t.scoreZones.veryLow
}

const getLocalizedAlert = (score: number | undefined, decision: Decision, t: ReturnType<typeof getTranslations>) => {
  if (score !== undefined && score >= 80) {
    return { title: t.dashboard.alertTitles.takeProfit, message: t.dashboard.alertMessages.takeProfit, reaction: t.dashboard.alertReactions.takeProfit }
  }
  if (score !== undefined && score >= 75) {
    return { title: t.dashboard.alertTitles.strong, message: t.dashboard.alertMessages.strong, reaction: t.dashboard.alertReactions.strong }
  }
  if (score !== undefined && score >= 65) {
    return { title: t.dashboard.alertTitles.push, message: t.dashboard.alertMessages.push, reaction: t.dashboard.alertReactions.push }
  }
  if (score !== undefined && score >= 60) {
    return { title: t.dashboard.alertTitles.caution, message: t.dashboard.alertMessages.caution, reaction: t.dashboard.alertReactions.caution }
  }
  if (decision === 'HOLD_OR_BUY') {
    return { title: t.dashboard.alertTitles.hold, message: t.dashboard.alertMessages.hold, reaction: t.dashboard.alertReactions.hold }
  }
  return { title: t.dashboard.alertTitles.wait, message: t.dashboard.alertMessages.wait, reaction: t.dashboard.alertReactions.wait }
}

function SimpleAlertCard({
  scores,
  highlights = [],
  zoneText,
  onShowDetails,
  expanded,
  tooltips,
  status = 'ready',
  statusMessage,
  onRetry,
  isRetrying = false,
}: Props) {
  const language = useAppLanguage()
  const t = getTranslations(language)
  const d = t.dashboard
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const showConfirmed = status === 'ready' || status === 'refreshing'
  const totalScore = scores?.total
  const alert = getAlertState(showConfirmed ? totalScore : undefined)
  const localizedAlert = getLocalizedAlert(showConfirmed ? totalScore : undefined, alert.decision, t)
  const cardBackground = isDark ? '#2b2f38' : darken(alert.color, 0.04)
  const borderColor = isDark ? 'rgba(255,255,255,0.08)' : alpha(theme.palette.text.primary, 0.1)
  const textPrimary = isDark ? '#ffffff' : 'rgba(0, 0, 0, 0.85)'
  const textSecondary = isDark ? '#d2d2d2' : 'rgba(0, 0, 0, 0.75)'
  const localizedZoneText = getLocalizedZoneText(showConfirmed ? totalScore : undefined, t)

  return (
    <Card
      sx={{
        background: cardBackground,
        border: `1px solid ${borderColor}`,
        boxShadow: isDark
          ? '0 14px 40px rgba(0, 0, 0, 0.38)'
          : `0 12px 30px ${alpha(theme.palette.text.primary, 0.08)}`,
      }}
    >
      <CardContent>
        <Stack spacing={2.25}>
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
          <Tooltip title={tooltips.simple.alert} arrow>
            <Typography variant="overline" color={textSecondary}>
              {d.simpleAlert}
            </Typography>
          </Tooltip>
          <Stack direction="row" alignItems="center" spacing={2.25}>
            {status === 'loading' ? (
              <Skeleton variant="circular" width={40} height={40} />
            ) : (
              <AnimatedSignalLight decision={alert.decision} />
            )}
            <Stack spacing={0.75} flex={1}>
              {status === 'loading' ? (
                <>
                  <Skeleton variant="text" width="60%" />
                  <Skeleton variant="text" width="80%" />
                </>
              ) : (
                <>
                  <Typography variant="h6" fontWeight={700} color={textPrimary}>
                    {showConfirmed ? localizedAlert.title : d.uncertainTitle}
                  </Typography>
                  <Typography variant="body2" color={textSecondary}>
                    {showConfirmed ? localizedAlert.reaction : d.uncertainReaction}
                  </Typography>
                </>
              )}
            </Stack>
            {status === 'refreshing' && <Chip size="small" color="info" label={d.refreshing} />}
          </Stack>
          <Typography variant="body1" color={textPrimary}>
            {status === 'loading' ? d.loading : showConfirmed ? localizedAlert.message : d.uncertainScore}
          </Typography>
          <Typography variant="body2" color={textSecondary}>
            {status === 'loading'
              ? d.waitLoading
              : language === 'en'
                ? localizedZoneText
                : zoneText ?? localizedZoneText}
          </Typography>
          {highlights.length > 0 && (
            <Box
              sx={{
                p: 2,
                borderRadius: 2,
                backgroundColor: alpha(theme.palette.background.default, 0.35),
                border: `1px solid ${alpha(theme.palette.text.primary, 0.08)}`,
              }}
            >
              <Tooltip title={tooltips.simple.points} arrow>
                <Typography variant="subtitle2" color={textSecondary} gutterBottom>
                  {d.todayPoints}
                </Typography>
              </Tooltip>
              <Stack spacing={1}>
                {highlights.map((h, idx) => (
                  <Stack direction="row" spacing={1} alignItems="flex-start" key={`${h.icon}-${idx}`}>
                    <Typography variant="body1" component="span" aria-hidden>
                      {h.icon}
                    </Typography>
                    <Typography variant="body2" component="span" color={textPrimary}>
                      {h.text}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
            </Box>
          )}
          <Divider light />
          <Button
            variant="outlined"
            color="inherit"
            endIcon={<ArrowForwardIcon />}
            onClick={onShowDetails}
            sx={{ alignSelf: 'flex-start' }}
          >
            {expanded ? d.detailsClose : d.detailsOpen}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

export default SimpleAlertCard
