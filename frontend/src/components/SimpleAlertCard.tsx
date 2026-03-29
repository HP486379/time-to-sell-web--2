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
import { getAlertState, getScoreZoneText } from '../utils/alertState'
import { AnimatedSignalLight } from './AnimatedSignalLight'

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
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const showConfirmed = status === 'ready' || status === 'refreshing'
  const totalScore = scores?.total
  const alert = getAlertState(showConfirmed ? totalScore : undefined)
  const cardBackground = isDark ? '#2b2f38' : darken(alert.color, 0.04)
  const borderColor = isDark ? 'rgba(255,255,255,0.08)' : alpha(theme.palette.text.primary, 0.1)
  const textPrimary = isDark ? '#ffffff' : 'rgba(0, 0, 0, 0.85)'
  const textSecondary = isDark ? '#d2d2d2' : 'rgba(0, 0, 0, 0.75)'

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
                    再取得
                  </Button>
                ) : undefined
              }
            >
              <Typography variant="subtitle2" component="div">
                ⚠ 一部データ取得中
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {statusMessage ?? '価格履歴の取得が未完了のため、現在のスコアは参考値です。'}
              </Typography>
              {isRetrying && (
                <Typography variant="caption" color="text.secondary">
                  再試行中…
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
                    再取得
                  </Button>
                ) : undefined
              }
            >
              <Typography variant="subtitle2" component="div">
                ❌ データ取得に失敗しました
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {statusMessage ?? '時間をおいて再取得してください。'}
              </Typography>
            </Alert>
          )}
          <Tooltip title={tooltips.simple.alert} arrow>
            <Typography variant="overline" color={textSecondary}>
              シンプル・アラート
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
                    {showConfirmed ? alert.title : '未確定データを確認中'}
                  </Typography>
                  <Typography variant="body2" color={textSecondary}>
                    {showConfirmed ? alert.reaction : 'データが揃い次第、確定スコアを表示します。'}
                  </Typography>
                </>
              )}
            </Stack>
            {status === 'refreshing' && <Chip size="small" color="info" label="更新中…" />}
          </Stack>
          <Typography variant="body1" color={textPrimary}>
            {status === 'loading' ? '⏳ 計算中…' : showConfirmed ? alert.message : '現在のスコアは未確定です。'}
          </Typography>
          <Typography variant="body2" color={textSecondary}>
            {status === 'loading'
              ? '計算完了までしばらくお待ちください。'
              : zoneText ?? getScoreZoneText(showConfirmed ? totalScore : undefined)}
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
                  今日のポイント
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
            {expanded ? '閉じる' : 'くわしく見る ≫'}
          </Button>
        </Stack>
      </CardContent>
    </Card>
  )
}

export default SimpleAlertCard
