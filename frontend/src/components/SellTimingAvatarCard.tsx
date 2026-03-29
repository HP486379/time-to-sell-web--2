import { Card, CardContent, Typography, Box } from '@mui/material'
import UridokiKunAvatar from './UridokiKunAvatar'
import { type Decision } from '../domain/decision'

export type SellTimingAvatarCardProps = {
  decision: Decision
}

export default function SellTimingAvatarCard({ decision }: SellTimingAvatarCardProps) {
  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ height: '100%', display: 'flex', flexDirection: 'column', gap: 1 }}>
        <Box sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 1.5 }}>
          <Box textAlign="center" sx={{ width: '100%' }}>
            <Box
              position="relative"
              display="inline-flex"
              sx={{
                overflow: 'visible',
                width: 420,
                height: 420,
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <UridokiKunAvatar decision={decision} size={360} animated />
            </Box>
            <Typography
              variant="subtitle2"
              color="text.secondary"
              sx={{ mt: 1, textAlign: 'center', whiteSpace: 'normal', wordBreak: 'break-word' }}
            >
              売り時くん
            </Typography>
            <Typography
              variant="caption"
              color="text.secondary"
              sx={{ display: 'block', mt: 0.5, textAlign: 'center', whiteSpace: 'normal', wordBreak: 'break-word' }}
            >
              スコアに応じて表示が変わります
            </Typography>
          </Box>
        </Box>
      </CardContent>
    </Card>
  )
}
