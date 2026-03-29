import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

type Placement = 'top' | 'bottom' | 'left' | 'right'

type HoverTooltipProps = {
  content: string
  children: React.ReactElement
  placement?: Placement
  offset?: number
}

const DEFAULT_OFFSET = 10
const ARROW_SIZE = 6
const VIEWPORT_PADDING = 8

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max)
}

export default function HoverTooltip({
  content,
  children,
  placement = 'bottom',
  offset = DEFAULT_OFFSET,
}: HoverTooltipProps) {
  const anchorRef = useRef<HTMLSpanElement | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const [visible, setVisible] = useState(false)
  const [position, setPosition] = useState({ top: 0, left: 0 })
  const hideTimeoutRef = useRef<number | null>(null)

  useEffect(() => {
    return () => {
      if (hideTimeoutRef.current !== null) {
        window.clearTimeout(hideTimeoutRef.current)
      }
    }
  }, [])

  const scheduleHide = () => {
    if (hideTimeoutRef.current !== null) {
      window.clearTimeout(hideTimeoutRef.current)
    }
    hideTimeoutRef.current = window.setTimeout(() => setVisible(false), 1200)
  }

  const handleShow = () => {
    if (hideTimeoutRef.current !== null) {
      window.clearTimeout(hideTimeoutRef.current)
    }
    setVisible(true)
  }

  const handleHide = () => {
    if (hideTimeoutRef.current !== null) {
      window.clearTimeout(hideTimeoutRef.current)
    }
    setVisible(false)
  }

  useLayoutEffect(() => {
    if (!visible) return
    const anchor = anchorRef.current
    const tooltip = tooltipRef.current
    if (!anchor || !tooltip) return

    const rect = anchor.getBoundingClientRect()
    const tooltipRect = tooltip.getBoundingClientRect()
    const next = { top: 0, left: 0 }

    switch (placement) {
      case 'top':
        next.top = rect.top - tooltipRect.height - offset
        next.left = rect.left + rect.width / 2 - tooltipRect.width / 2
        break
      case 'left':
        next.top = rect.top + rect.height / 2 - tooltipRect.height / 2
        next.left = rect.left - tooltipRect.width - offset
        break
      case 'right':
        next.top = rect.top + rect.height / 2 - tooltipRect.height / 2
        next.left = rect.right + offset
        break
      case 'bottom':
      default:
        next.top = rect.bottom + offset
        next.left = rect.left + rect.width / 2 - tooltipRect.width / 2
        break
    }

    next.left = clamp(next.left, VIEWPORT_PADDING, window.innerWidth - tooltipRect.width - VIEWPORT_PADDING)
    next.top = clamp(next.top, VIEWPORT_PADDING, window.innerHeight - tooltipRect.height - VIEWPORT_PADDING)

    setPosition(next)
  }, [visible, placement, offset])

  useEffect(() => {
    if (!visible) return
    const handleReposition = () => {
      const anchor = anchorRef.current
      const tooltip = tooltipRef.current
      if (!anchor || !tooltip) return
      const rect = anchor.getBoundingClientRect()
      const tooltipRect = tooltip.getBoundingClientRect()
      let top = 0
      let left = 0

      switch (placement) {
        case 'top':
          top = rect.top - tooltipRect.height - offset
          left = rect.left + rect.width / 2 - tooltipRect.width / 2
          break
        case 'left':
          top = rect.top + rect.height / 2 - tooltipRect.height / 2
          left = rect.left - tooltipRect.width - offset
          break
        case 'right':
          top = rect.top + rect.height / 2 - tooltipRect.height / 2
          left = rect.right + offset
          break
        case 'bottom':
        default:
          top = rect.bottom + offset
          left = rect.left + rect.width / 2 - tooltipRect.width / 2
          break
      }

      left = clamp(left, VIEWPORT_PADDING, window.innerWidth - tooltipRect.width - VIEWPORT_PADDING)
      top = clamp(top, VIEWPORT_PADDING, window.innerHeight - tooltipRect.height - VIEWPORT_PADDING)
      setPosition({ top, left })
    }

    window.addEventListener('scroll', handleReposition, true)
    window.addEventListener('resize', handleReposition)
    return () => {
      window.removeEventListener('scroll', handleReposition, true)
      window.removeEventListener('resize', handleReposition)
    }
  }, [visible, placement, offset])

  const tooltip = visible
    ? createPortal(
        <div
          ref={tooltipRef}
          style={{
            position: 'fixed',
            top: `${position.top}px`,
            left: `${position.left}px`,
            zIndex: 20000,
            pointerEvents: 'none',
            opacity: visible ? 1 : 0,
            transform: visible ? 'translateY(0px)' : 'translateY(4px)',
            transition: 'opacity 0.12s ease, transform 0.12s ease',
            background: 'rgba(20, 20, 20, 0.95)',
            color: '#fff',
            padding: '8px 10px',
            borderRadius: '8px',
            boxShadow: '0 8px 18px rgba(0,0,0,0.35)',
            maxWidth: '260px',
            fontSize: '0.75rem',
            lineHeight: 1.4,
          }}
        >
          {content}
          <div
            style={{
              position: 'absolute',
              width: 0,
              height: 0,
              borderStyle: 'solid',
              ...(placement === 'top'
                ? {
                    borderWidth: `${ARROW_SIZE}px ${ARROW_SIZE}px 0 ${ARROW_SIZE}px`,
                    borderColor: 'rgba(20, 20, 20, 0.95) transparent transparent transparent',
                    bottom: -ARROW_SIZE,
                    left: '50%',
                    transform: 'translateX(-50%)',
                  }
                : placement === 'left'
                  ? {
                      borderWidth: `${ARROW_SIZE}px 0 ${ARROW_SIZE}px ${ARROW_SIZE}px`,
                      borderColor: 'transparent transparent transparent rgba(20, 20, 20, 0.95)',
                      right: -ARROW_SIZE,
                      top: '50%',
                      transform: 'translateY(-50%)',
                    }
                  : placement === 'right'
                    ? {
                        borderWidth: `${ARROW_SIZE}px ${ARROW_SIZE}px ${ARROW_SIZE}px 0`,
                        borderColor: 'transparent rgba(20, 20, 20, 0.95) transparent transparent',
                        left: -ARROW_SIZE,
                        top: '50%',
                        transform: 'translateY(-50%)',
                      }
                    : {
                        borderWidth: `0 ${ARROW_SIZE}px ${ARROW_SIZE}px ${ARROW_SIZE}px`,
                        borderColor: 'transparent transparent rgba(20, 20, 20, 0.95) transparent',
                        top: -ARROW_SIZE,
                        left: '50%',
                        transform: 'translateX(-50%)',
                      }),
            }}
          />
        </div>,
        document.body,
      )
    : null

  return (
    <>
      <span
        ref={anchorRef}
        onMouseEnter={handleShow}
        onMouseLeave={handleHide}
        onFocus={handleShow}
        onBlur={handleHide}
        onTouchStart={handleShow}
        onTouchEnd={scheduleHide}
        style={{ display: 'inline-flex' }}
      >
        {children}
      </span>
      {tooltip}
    </>
  )
}
