import React, { useEffect, useMemo, useState } from 'react'
import {
  Card,
  CardContent,
  Typography,
  Stack,
  Chip,
  Tooltip,
  Box,
  Divider,
  Skeleton,
  Alert,
  Collapse,
  IconButton,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import dayjs from 'dayjs'
import 'dayjs/locale/ja'
import type { EventItem } from '../apis'

// tooltips の厳密な型は知らないので any にしておく
type EventTooltips = any

type Props = {
  // スコア計算側の event_details（E_adj など）※あれば使う
  eventDetails?: any
  // /api/events から取得したイベント一覧
  events?: EventItem[]
  // ローディング・エラー状態
  isLoading?: boolean
  error?: string | null
  // ツールチップ文言
  tooltips?: EventTooltips
}

dayjs.locale('ja')

const EventList: React.FC<Props> = ({ eventDetails, events, isLoading, error, tooltips }) => {
  const title = tooltips?.events?.title ?? '重要イベント'

  // ====== manual > heuristic のマージ ======
  const mergedEvents = useMemo(() => {
    if (!Array.isArray(events) || events.length === 0) return []

    const normalizedEvents = events.filter((e): e is EventItem => {
      return !!e && typeof e === 'object' && typeof e.date === 'string' && typeof e.name === 'string'
    })

    const manual = normalizedEvents.filter((e) => e.source === 'manual')
    const heuristic = normalizedEvents.filter((e) => e.source !== 'manual')

    // 同じ name & date が manual にあるものは heuristic を捨てる
    const isDuplicated = (h: EventItem) =>
      manual.some((m) => m.name === h.name && m.date === h.date)

    const cleanedHeuristic = heuristic.filter((h) => !isDuplicated(h))

    const merged = [...manual, ...cleanedHeuristic]

    // 日付昇順、同じ日なら importance 降順、最後に manual を優先
    return merged.sort((a, b) => {
      const da = dayjs(a.date)
      const db = dayjs(b.date)
      if (da.isBefore(db)) return -1
      if (da.isAfter(db)) return 1
      if (a.importance !== b.importance) return b.importance - a.importance
      if (a.source === b.source) return 0
      return a.source === 'manual' ? -1 : 1
    })
  }, [events])

  const today = dayjs().startOf('day')

  // 直近イベントの index（今日か未来で一番近いもの）
  const firstUpcomingIndex = useMemo(() => {
    if (!mergedEvents.length) return -1
    return mergedEvents.findIndex((e) => {
      const d = dayjs(e.date)
      return d.isSame(today, 'day') || d.isAfter(today, 'day')
    })
  }, [mergedEvents, today])

  const nextEvent =
    firstUpcomingIndex >= 0 && firstUpcomingIndex < mergedEvents.length
      ? mergedEvents[firstUpcomingIndex]
      : null

  const nextDiffDays =
    nextEvent != null ? dayjs(nextEvent.date).startOf('day').diff(today, 'day') : null

  // 「どのイベントが next か」をキーで判定
  const nextEventKey =
    nextEvent != null ? `${nextEvent.name}|${nextEvent.date}|${nextEvent.source}` : null

  // これから/過去 で分割
  const upcomingEvents = mergedEvents.filter((e) => !dayjs(e.date).isBefore(today, 'day'))
  const pastEvents = mergedEvents.filter((e) => dayjs(e.date).isBefore(today, 'day'))

  // アコーディオンの開閉
  const [showUpcoming, setShowUpcoming] = useState(true)
  const [showPast, setShowPast] = useState(false)

  const eventAdjust = eventDetails?.E_adj ?? null

  const formatDateJp = (d: string) => {
    const t = dayjs(d)
    if (!t.isValid()) return d
    return t.format('YYYY/MM/DD (ddd)')
  }

  const getImportanceChip = (imp?: number) => {
    const value = typeof imp === 'number' ? imp : 3
    if (value >= 5) {
      return <Chip size="small" color="error" label="★★★ 超重要" />
    }
    if (value >= 4) {
      return <Chip size="small" color="warning" label="★★ 重要" />
    }
    if (value >= 3) {
      return <Chip size="small" color="info" label="★ 注目" />
    }
    return <Chip size="small" variant="outlined" label="参考" />
  }

  const getSourceChip = (source?: string) => {
    if (source === 'manual' || !source) {
      return null
    }
    return (
      <Chip
        size="small"
        variant="outlined"
        label="推定"
      />
    )
  }

  const renderEventRow = (ev: EventItem) => {
    const key = `${ev.name}|${ev.date}|${ev.source}`
    const isPast = dayjs(ev.date).isBefore(today, 'day')
    const isNext = key === nextEventKey
    const sourceChip = getSourceChip(ev.source)

    return (
      <Box
        key={key}
        sx={(theme) => ({
          borderRadius: 1.5,
          px: 1.2,
          py: 0.8,
          display: 'flex',
          alignItems: 'flex-start',
          gap: 1,
          bgcolor: isNext
            ? theme.palette.mode === 'dark'
              ? 'rgba(144, 202, 249, 0.12)'
              : 'rgba(25, 118, 210, 0.06)'
            : 'transparent',
          opacity: isPast ? 0.65 : 1,
        })}
      >
        <Box sx={{ minWidth: 110 }}>
          <Typography variant="body2" sx={{ fontWeight: isNext ? 600 : 400 }}>
            {formatDateJp(ev.date)}
          </Typography>
        </Box>
        <Box sx={{ flex: 1, minWidth: 0 }}>
          <Typography variant="body2" noWrap sx={{ fontWeight: isNext ? 600 : 400 }}>
            {ev.name}
          </Typography>
          {ev.description && (
            <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.4 }}>
              {ev.description}
            </Typography>
          )}
          <Stack direction="row" spacing={0.8} mt={0.4} flexWrap="wrap">
            {getImportanceChip(ev.importance)}
            {sourceChip}
            {isNext && (
              <Chip
                size="small"
                color="secondary"
                variant="outlined"
                label="直近"
              />
            )}
          </Stack>
        </Box>
      </Box>
    )
  }

  const renderSectionHeader = (
    label: string,
    open: boolean,
    toggle: () => void,
    extra?: React.ReactNode,
  ) => (
    <Box
      sx={(theme) => ({
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        mt: 1,
        mb: 0.5,
        px: 0.4,
        color: theme.palette.text.secondary,
      })}
    >
      <Stack direction="row" spacing={1} alignItems="center">
        <Typography variant="subtitle2">{label}</Typography>
        {extra}
      </Stack>
      <IconButton
        size="small"
        onClick={toggle}
        sx={{
          transform: open ? 'rotate(180deg)' : 'rotate(0deg)',
          transition: 'transform 0.15s ease-out',
        }}
      >
        <ExpandMoreIcon fontSize="small" />
      </IconButton>
    </Box>
  )

  const ymKey = (dateStr: string) => {
    const parsed = dayjs(dateStr)
    if (!parsed.isValid()) return dateStr
    return parsed.format('YYYY-MM')
  }

  const groupByMonth = (items: EventItem[]) => {
    const sorted = [...items].sort((a, b) => dayjs(a.date).diff(dayjs(b.date)))
    const groups: { ym: string; items: EventItem[] }[] = []
    for (const item of sorted) {
      const key = ymKey(item.date)
      const last = groups[groups.length - 1]
      if (last && last.ym === key) {
        last.items.push(item)
      } else {
        groups.push({ ym: key, items: [item] })
      }
    }
    return groups
  }

  const upcomingGroups = useMemo(() => groupByMonth(upcomingEvents), [upcomingEvents])

  const [openMonths, setOpenMonths] = useState<Record<string, boolean>>({})

  useEffect(() => {
    if (upcomingGroups.length === 0) return
    const currentYm = today.format('YYYY-MM')
    setOpenMonths((prev) => {
      const nextState = { ...prev }
      for (const group of upcomingGroups) {
        if (!(group.ym in nextState)) {
          nextState[group.ym] = group.ym === currentYm
        }
      }
      return nextState
    })
  }, [upcomingGroups, today])

  const formatMonthHeader = (ym: string, count: number) => {
    const parsed = dayjs(`${ym}-01`)
    const label = parsed.isValid() ? parsed.format('YYYY年MM月') : ym
    return `${label}（${count}件）`
  }

  return (
    <Card sx={{ height: '100%' }}>
      <CardContent sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
        {/* タイトル行 + イベント補正 */}
        <Stack direction="row" alignItems="center" justifyContent="space-between">
          <Tooltip title={title} arrow>
            <Typography variant="h6" component="div">
              重要イベント
            </Typography>
          </Tooltip>
          {eventAdjust !== null && (
            <Chip
              size="small"
              label={`イベント補正: ${eventAdjust.toFixed(1)} pt`}
              color={eventAdjust <= -3 ? 'error' : eventAdjust >= 3 ? 'success' : 'default'}
            />
          )}
        </Stack>

        {/* ② 次の重要イベントまであと◯日 */}
        {!isLoading && !error && nextEvent && (
          <Box
            sx={(theme) => ({
              px: 1,
              py: 0.75,
              borderRadius: 1.5,
              bgcolor:
                theme.palette.mode === 'dark'
                  ? 'rgba(144, 202, 249, 0.12)'
                  : 'rgba(25, 118, 210, 0.06)',
            })}
          >
            <Typography variant="caption" color="text.secondary">
              ⏰ 次の重要イベントまで
            </Typography>
            <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap">
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {nextDiffDays === 0
                  ? '本日'
                  : nextDiffDays === 1
                    ? 'あと 1 日'
                    : `あと ${nextDiffDays} 日`}
              </Typography>
              <Typography variant="body2">
                （{formatDateJp(nextEvent.date)} {nextEvent.name}）
              </Typography>
            </Stack>
          </Box>
        )}

        {/* ローディング & エラー */}
        {isLoading && (
          <Stack spacing={1.2} mt={1}>
            <Skeleton variant="text" height={24} />
            <Skeleton variant="text" height={24} />
            <Skeleton variant="text" height={24} />
          </Stack>
        )}

        {!isLoading && error && (
          <Alert severity="warning" sx={{ mt: 1 }}>
            イベント情報の取得に失敗しました：{error}
          </Alert>
        )}

        {/* イベント 0 件 */}
        {!isLoading && !error && mergedEvents.length === 0 && (
          <Typography variant="body2" color="text.secondary" mt={1}>
            現在、対象期間（直近1週間〜30日先）に登録されたイベントはありません。
          </Typography>
        )}

        {/* ④ アコーディオン（これから / 過去） */}
        {!isLoading && !error && mergedEvents.length > 0 && (
          <>
            {/* これからのイベント */}
            {upcomingEvents.length > 0 && (
              <>
                {renderSectionHeader(
                  'これからのイベント',
                  showUpcoming,
                  () => setShowUpcoming((v) => !v),
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${upcomingEvents.length} 件`}
                  />,
                )}
                <Collapse in={showUpcoming}>
                  <Stack spacing={1.0} mt={0.5}>
                    {upcomingGroups.map((group) => {
                      const isOpen = openMonths[group.ym] ?? false
                      return (
                        <Box key={group.ym}>
                          <Box
                            sx={(theme) => ({
                              display: 'flex',
                              alignItems: 'center',
                              justifyContent: 'space-between',
                              px: 0.4,
                              py: 0.2,
                              color: theme.palette.text.secondary,
                              borderRadius: 1,
                              cursor: 'pointer',
                              '&:hover': {
                                bgcolor:
                                  theme.palette.mode === 'dark'
                                    ? 'rgba(255, 255, 255, 0.06)'
                                    : 'rgba(0, 0, 0, 0.04)',
                              },
                            })}
                            onClick={() =>
                              setOpenMonths((prev) => ({
                                ...prev,
                                [group.ym]: !isOpen,
                              }))
                            }
                          >
                            <Typography variant="subtitle2">
                              {formatMonthHeader(group.ym, group.items.length)}
                            </Typography>
                            <IconButton
                              size="small"
                              sx={{
                                transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)',
                                transition: 'transform 0.15s ease-out',
                              }}
                            >
                              <ExpandMoreIcon fontSize="small" />
                            </IconButton>
                          </Box>
                          <Collapse in={isOpen}>
                            <Stack spacing={1.0} mt={0.5}>
                              {group.items.map((ev) => renderEventRow(ev))}
                            </Stack>
                          </Collapse>
                        </Box>
                      )
                    })}
                  </Stack>
                </Collapse>
              </>
            )}

            {/* 過去のイベント */}
            {pastEvents.length > 0 && (
              <>
                {renderSectionHeader(
                  '過去のイベント',
                  showPast,
                  () => setShowPast((v) => !v),
                  <Chip
                    size="small"
                    variant="outlined"
                    label={`${pastEvents.length} 件`}
                  />,
                )}
                <Collapse in={showPast}>
                  <Stack spacing={1.0} mt={0.5}>
                    {pastEvents.map((ev) => renderEventRow(ev))}
                  </Stack>
                </Collapse>
              </>
            )}

            <Divider sx={{ my: 1.5 }} />
          </>
        )}
      </CardContent>
    </Card>
  )
}

export default EventList
