import { Box, Typography } from '@mui/material'

interface Props {
  score?: number
}

function getBadge(score = 0) {
  if (score >= 80) return { color: '#22c55e', icon: '🟢', label: '高スコア' }
  if (score >= 60) return { color: '#3b82f6', icon: '🔵', label: 'やや高め' }
  if (score >= 40) return { color: '#facc15', icon: '🟡', label: '平均' }
  return { color: '#ef4444', icon: '🔴', label: '低め' }
}

export const ScoreBadge = ({ score }: Props) => {
  const info = getBadge(score ?? 0)
  return (
    <Box
      sx={{
        width: 72,
        height: 72,
        borderRadius: '50%',
        backgroundColor: info.color,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        boxShadow: '0 10px 24px rgba(0,0,0,0.12)',
        color: '#fff',
        flexShrink: 0,
      }}
      aria-label={`スコアバッジ: ${info.label}`}
      title={`スコアバッジ: ${info.label}`}
    >
      <Typography variant="h4" component="span">
        {info.icon}
      </Typography>
    </Box>
  )
}

export default ScoreBadge
