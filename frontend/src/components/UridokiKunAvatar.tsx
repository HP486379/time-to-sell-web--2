import React from 'react'
import type { Decision } from '../domain/decision'
import { DEFAULT_AVATAR_ALT, DEFAULT_AVATAR_SPRITE, type ScoreMaDays } from '../constants/maAvatarMap'

interface Props {
  decision: Decision
  size?: number
  animated?: boolean
  label?: string
  spriteUrl?: string
  scoreMaDays?: ScoreMaDays
}

const positionMap: Record<Decision, string> = {
  TAKE_PROFIT: '0% 0%',
  WAIT: '0% 100%',
  HOLD_OR_BUY: '100% 100%',
}

const levelLabels: Record<Decision, string> = {
  TAKE_PROFIT: '利確モード',
  WAIT: '様子見モード',
  HOLD_OR_BUY: '保有・買い増し寄り',
}

export const UridokiKunAvatar: React.FC<Props> = ({
  decision,
  size = 96,
  animated = false,
  label,
}) => {
  const ariaLabel = label ?? DEFAULT_AVATAR_ALT ?? levelLabels[decision]
  const fallback = 'linear-gradient(135deg, #1e293b, #0ea5e9)'
  const resolvedUrl = DEFAULT_AVATAR_SPRITE

  return (
    <div
      className={`uridoki-kun-avatar uridoki-kun-${decision}`}
      role="img"
      aria-label={ariaLabel}
      title={ariaLabel}
      style={{
        overflow: 'visible',
        width: size,
        height: size,
        maxWidth: '100%',
        backgroundImage: resolvedUrl ? `url(${resolvedUrl})` : fallback,
        backgroundSize: resolvedUrl ? '200% 200%' : 'contain',
        backgroundPosition: resolvedUrl ? positionMap[decision] : 'center',
        backgroundRepeat: 'no-repeat',
        borderRadius: 12,
        boxShadow: animated ? '0 10px 25px rgba(0,0,0,0.12)' : undefined,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        objectFit: 'contain',
      }}
    />
  )
}

export default UridokiKunAvatar
