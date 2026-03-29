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
import { getScoreZoneText } from '../utils/alertState'

type EvalStatus = 'loading' | 'ready' | 'degraded' | 'error' | 'refreshing'

interface ScoreSummaryCardProps {
  scores?: {
    total: number
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
  overallScoreNoteTitle = '総合スコア（統合判断）とは',
  overallScoreNoteLines = [
    'テクニカル・マクロ・イベント要因を統合した「今どうすべきか」の結論です。',
    '時間軸別の評価（短期/中期/長期）とは別指標のため、一致しない場合があります。',
  ],
}: ScoreSummaryCardProps) {
  const theme = useTheme()
  const isDark = theme.palette.mode === 'dark'
  const gradientStart = isDark ? '#101726' : alpha(theme.palette.primary.light, 0.2)
  const gradientEnd = isDark ? '#0c1b34' : alpha(theme.palette.secondary.light, 0.16)
  const showConfirmed = status === 'ready' || status === 'refreshing'
  const totalScore = scores?.total
  const zoneTextValue = zoneText ?? getScoreZoneText(showConfirmed ? totalScore : undefined)
  const showDetailsToggle = Boolean(onShowDetails) && expanded !== undefined

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

          <Box
            display="grid"
            gridTemplateColumns={{ xs: '1fr', md: 'minmax(0, 1fr) minmax(260px, 0.9fr)' }}
            gap={2}
            alignItems="start"
          >
            <Stack spacing={0.75}>
              <Tooltip title={tooltips.score.total} arrow>
                <Typography variant="overline" color="text.secondary" component="div">
                  総合スコア
                </Typography>
              </Tooltip>
              <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
                {status === 'loading' ? (
                  <Skeleton variant="text" width={120} height={44} />
                ) : (
                  <Typography variant="h3" color="primary.main" fontWeight={700}>
                    {showConfirmed && totalScore !== undefined ? totalScore.toFixed(1) : '--'}
                  </Typography>
                )}
                {status === 'refreshing' && <Chip size="small" color="info" label="更新中…" />}
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
                {overallScoreNoteTitle}
              </Typography>
              <Stack spacing={0.5} mt={0.75}>
                {overallScoreNoteLines.map((line, index) => (
                  <Typography key={`overall-score-note-${index}`} variant="caption" color="text.secondary">
                    {line}
                  </Typography>
                ))}
              </Stack>
            </Box>
          </Box>

          <Typography variant="overline" color="text.secondary" component="div">
            出口接近度
          </Typography>
          <Tooltip title={tooltips.score.label} arrow>
            <Typography variant="subtitle1" color="text.secondary" component="div">
              {showConfirmed ? scores?.label ?? '計算待ち' : status === 'degraded' ? '未確定' : '計算中'}
            </Typography>
          </Tooltip>
          <Typography variant="body2" color="text.secondary">
            {status === 'loading' ? '⏳ 計算中…' : zoneTextValue}
          </Typography>

          {showDetailsToggle && (
            <>
              <Divider />
              <Button variant="outlined" color="inherit" onClick={onShowDetails} sx={{ alignSelf: 'flex-start' }}>
                {expanded ? '閉じる' : 'くわしく見る ≫'}
              </Button>
            </>
          )}
        </Stack>
      </CardContent>
    </Card>
  )
}

export default ScoreSummaryCard
