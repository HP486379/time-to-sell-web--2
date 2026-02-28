import { useEffect, useMemo, useRef, useState } from 'react'
import {
  Grid,
  Card,
  CardContent,
  Typography,
  Stack,
  Alert,
  Tooltip,
  Box,
  IconButton,
  Collapse,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Tabs,
  Tab,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  TextField,
  Skeleton,
  LinearProgress,
} from '@mui/material'
import axios from 'axios'
import dayjs from 'dayjs'
import { AnimatePresence, motion } from 'framer-motion'
import {
  EvaluateRequest,
  EvaluateResponse,
  FundNavResponse,
  SyntheticNavResponse,
  PricePoint,
} from '../types/api'
import ScoreSummaryCard from './ScoreSummaryCard'
import PositionForm from './PositionForm'
import PriceChart from './PriceChart'
import MacroCards from './MacroCards'
import EventList from './EventList'
import { buildTooltips } from '../tooltipTexts'
import RefreshIcon from '@mui/icons-material/Refresh'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import SimpleAlertCard from './SimpleAlertCard'
import HoverTooltip from './HoverTooltip'
import { type ScoreMaDays } from '../constants/maAvatarMap'
import { INDEX_LABELS, PRICE_TITLE_MAP, type IndexType } from '../types/index'
import { getScoreZoneText } from '../utils/alertState'
import SellTimingAvatarCard from './SellTimingAvatarCard'
import { decideSellAction } from '../domain/sellDecision'

// ★ 追加：イベント API 用
import { fetchEvents, type EventItem } from '../apis'

const apiBase =
  import.meta.env.VITE_API_BASE ||
  (typeof window !== 'undefined' ? window.location.origin : 'http://localhost:8000')

const apiClient = axios.create({
  baseURL: apiBase,
})

const defaultRequest: EvaluateRequest = {
  total_quantity: 77384,
  avg_cost: 21458,
  index_type: 'SP500',
  score_ma: 200,
}

const REFRESH_INTERVAL_MS = 5 * 60 * 1000

type DisplayMode = 'pro' | 'simple'
type StartOption = '1m' | '3m' | '6m' | '1y' | '3y' | '5y' | 'max' | 'custom'
type PriceDisplayMode = 'normalized' | 'actual'
type EvalStatus = 'loading' | 'ready' | 'degraded' | 'error' | 'refreshing'

const reasonLabelMap: Record<string, string> = {
  PRICE_HISTORY_EMPTY: '価格履歴を取得できていません',
  PRICE_HISTORY_SHORT: '過去データが不足しています',
  PRICE_HISTORY_UNAVAILABLE: '価格履歴取得が一時的に不安定です',
  TECHNICAL_FALLBACK_ZERO: 'テクニカル指標を再計算中です',
  TECHNICAL_CALC_ERROR: 'テクニカル計算に失敗しました',
  TECHNICAL_UNAVAILABLE: 'テクニカル指標が取得できません',
  MACRO_UNAVAILABLE: 'マクロ指標の取得に失敗しました',
  EVENTS_UNAVAILABLE: 'イベント情報の取得に失敗しました',
}

const motionVariants = {
  initial: { opacity: 0, y: -10 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: -10 },
}

const chartMotion = {
  initial: { opacity: 0.6 },
  animate: { opacity: 1 },
  exit: { opacity: 0.6 },
}

const calculateFallbackTechnicalScore = (series: PricePoint[]): number | null => {
  if (!series.length) return null
  const latest = series[series.length - 1]

  const indicators = [
    { ma: latest.ma20, weight: 0.25 },
    { ma: latest.ma60, weight: 0.35 },
    { ma: latest.ma200, weight: 0.4 },
  ].filter((item) => item.ma !== null)

  if (!indicators.length) return null

  const totalWeight = indicators.reduce((sum, item) => sum + item.weight, 0)
  const weightedScore = indicators.reduce((sum, item) => {
    const signal = latest.close >= (item.ma as number) ? 100 : 0
    return sum + signal * item.weight
  }, 0)

  return roundToTwo(weightedScore / totalWeight)
}

const withFallbackScores = (res: EvaluateResponse, series: PricePoint[]): EvaluateResponse => {
  const reasons = res.reasons ?? []
  if (!reasons.includes('TECHNICAL_UNAVAILABLE')) return res

  const fallbackTechnical = calculateFallbackTechnicalScore(series)
  if (fallbackTechnical === null) return res

  const fallbackTotal = roundToTwo(
    fallbackTechnical * 0.45 +
      (res.scores?.macro ?? 0) * 0.45 +
      (res.scores?.event_adjustment ?? 0) * 0.1,
  )

  return {
    ...res,
    status: 'ready',
    reasons,
    scores: {
      ...res.scores,
      technical: fallbackTechnical,
      total: fallbackTotal,
    },
  }
}

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value)

const hasUsableScores = (res: EvaluateResponse): boolean =>
  isFiniteNumber(res?.scores?.technical) &&
  isFiniteNumber(res?.scores?.macro) &&
  isFiniteNumber(res?.scores?.event_adjustment) &&
  isFiniteNumber(res?.scores?.total)

const normalizeEvaluateResponse = (res: EvaluateResponse, series: PricePoint[]): EvaluateResponse => {
  const withFallback = withFallbackScores(res, series)
  if (hasUsableScores(withFallback)) return withFallback

  return {
    ...withFallback,
    status: 'degraded',
    scores: {
      ...withFallback.scores,
      technical: isFiniteNumber(withFallback.scores?.technical) ? withFallback.scores.technical : 0,
      macro: isFiniteNumber(withFallback.scores?.macro) ? withFallback.scores.macro : 0,
      event_adjustment: isFiniteNumber(withFallback.scores?.event_adjustment)
        ? withFallback.scores.event_adjustment
        : 0,
      total: isFiniteNumber(withFallback.scores?.total) ? withFallback.scores.total : 0,
      label: withFallback.scores?.label ?? '計算中',
    },
    reasons: [...(withFallback.reasons ?? []), 'TECHNICAL_UNAVAILABLE'],
  }
}

type ViewKey = 'short' | 'mid' | 'long'

type BreakdownSlice = {
  scores?: Partial<EvaluateResponse['scores']>
  technical_details?: Partial<EvaluateResponse['technical_details']>
  macro_details?: Partial<EvaluateResponse['macro_details']>
}

type ActiveBreakdown = {
  scores: EvaluateResponse['scores']
  technical: EvaluateResponse['technical_details'] | undefined
  macro: EvaluateResponse['macro_details'] | undefined
  isFallback: boolean
}

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null

const parseBreakdownSlice = (value: unknown): BreakdownSlice | null => {
  if (!isRecord(value)) return null

  const scoresSource = isRecord(value.scores) ? value.scores : value
  const technicalSource = isRecord(value.technical_details)
    ? value.technical_details
    : isRecord(value.technical) && typeof value.technical.d === 'number'
      ? value.technical
      : null
  const macroSource = isRecord(value.macro_details)
    ? value.macro_details
    : isRecord(value.macro) && typeof value.macro.M === 'number'
      ? value.macro
      : null

  const scoreSlice: BreakdownSlice['scores'] = {
    technical: typeof scoresSource.technical === 'number' ? scoresSource.technical : undefined,
    macro: typeof scoresSource.macro === 'number' ? scoresSource.macro : undefined,
    event_adjustment:
      typeof scoresSource.event_adjustment === 'number' ? scoresSource.event_adjustment : undefined,
  }

  const technicalSlice = technicalSource
    ? {
        d: typeof technicalSource.d === 'number' ? technicalSource.d : undefined,
        T_base: typeof technicalSource.T_base === 'number' ? technicalSource.T_base : undefined,
        T_trend: typeof technicalSource.T_trend === 'number' ? technicalSource.T_trend : undefined,
        T_conv_adj: typeof technicalSource.T_conv_adj === 'number' ? technicalSource.T_conv_adj : undefined,
        convergence: isRecord(technicalSource.convergence)
          ? (technicalSource.convergence as EvaluateResponse['technical_details']['convergence'])
          : undefined,
        multi_ma: isRecord(technicalSource.multi_ma)
          ? (technicalSource.multi_ma as EvaluateResponse['technical_details']['multi_ma'])
          : undefined,
      }
    : undefined

  const macroSlice = macroSource
    ? {
        p_r: typeof macroSource.p_r === 'number' ? macroSource.p_r : undefined,
        p_cpi: typeof macroSource.p_cpi === 'number' ? macroSource.p_cpi : undefined,
        p_vix: typeof macroSource.p_vix === 'number' ? macroSource.p_vix : undefined,
        M: typeof macroSource.M === 'number' ? macroSource.M : undefined,
      }
    : undefined

  const hasAnyScore = Object.values(scoreSlice).some((v) => typeof v === 'number')
  const hasAnyTechnical = technicalSlice && Object.values(technicalSlice).some((v) => v !== undefined)
  const hasAnyMacro = macroSlice && Object.values(macroSlice).some((v) => v !== undefined)

  if (!hasAnyScore && !hasAnyTechnical && !hasAnyMacro) return null
  return { scores: scoreSlice, technical_details: technicalSlice, macro_details: macroSlice }
}

const getActiveBreakdown = (
  viewKey: ViewKey,
  response: EvaluateResponse | null,
): ActiveBreakdown | null => {
  if (!response) return null

  const fallback: ActiveBreakdown = {
    scores: response.scores,
    technical: response.technical_details,
    macro: response.macro_details,
    isFallback: true,
  }

  const containerKeys = [
    'period_breakdowns',
    'period_details',
    'period_components',
    'period_scores_detail',
  ] as const

  const sourceRecord = response as unknown as Record<string, unknown>
  let slice: BreakdownSlice | null = null

  for (const key of containerKeys) {
    const container = sourceRecord[key]
    if (!isRecord(container)) continue
    slice = parseBreakdownSlice(container[viewKey])
    if (slice) break
  }

  if (!slice) return fallback

  return {
    scores: {
      ...response.scores,
      technical: slice.scores?.technical ?? response.scores.technical,
      macro: slice.scores?.macro ?? response.scores.macro,
      event_adjustment: slice.scores?.event_adjustment ?? response.scores.event_adjustment,
      total: response.scores.total,
      label: response.scores.label,
      period_total: response.scores.period_total,
    },
    technical: {
      ...response.technical_details,
      ...(slice.technical_details ?? {}),
    },
    macro: {
      ...response.macro_details,
      ...(slice.macro_details ?? {}),
    },
    isFallback: false,
  }
}

function DashboardPage({ displayMode }: { displayMode: DisplayMode }) {
  const [responses, setResponses] = useState<Partial<Record<IndexType, EvaluateResponse>>>({})
  const [error, setError] = useState<string | null>(null)
  const [syntheticNav, setSyntheticNav] = useState<SyntheticNavResponse | null>(null)
  const [fundNav, setFundNav] = useState<FundNavResponse | null>(null)
  const [lastRequest, setLastRequest] = useState<EvaluateRequest>(defaultRequest)
  const [viewDays, setViewDays] = useState<ScoreMaDays>(defaultRequest.score_ma as ScoreMaDays)
  const [indexType, setIndexType] = useState<IndexType>('SP500')
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const [showDetails, setShowDetails] = useState(false)
  const [startOption, setStartOption] = useState<StartOption>('max')
  const [customStart, setCustomStart] = useState('')
  const [priceDisplayMode, setPriceDisplayMode] = useState<PriceDisplayMode>('normalized')
  const [positionDialogOpen, setPositionDialogOpen] = useState(false)
  const [priceSeriesMap, setPriceSeriesMap] = useState<Partial<Record<IndexType, PricePoint[]>>>({})
  const [isEvalRetrying, setIsEvalRetrying] = useState(false)
  const [evalStatusMap, setEvalStatusMap] = useState<Partial<Record<IndexType, EvalStatus>>>({})
  const [evalReasonsMap, setEvalReasonsMap] = useState<Partial<Record<IndexType, string[]>>>({})
  const [evalStatusMessageMap, setEvalStatusMessageMap] = useState<Partial<Record<IndexType, string>>>({})
  const priceReqSeqRef = useRef(0)
  const evalReqSeqRef = useRef(0)
  const evalRetryTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const latestEvalRequestIdRef = useRef<Partial<Record<IndexType, string>>>({})

  // ★ 追加：イベント用 state
  const [events, setEvents] = useState<EventItem[]>([])
  const [isEventsLoading, setIsEventsLoading] = useState(false)
  const [eventsError, setEventsError] = useState<string | null>(null)

  const tooltipTexts = useMemo(
    () => buildTooltips(indexType, lastRequest.score_ma),
    [indexType, lastRequest.score_ma],
  )

  const response = responses[indexType] ?? null
  const evalStatus = evalStatusMap[indexType] ?? (response ? 'ready' : 'loading')
  const evalReasons = evalReasonsMap[indexType] ?? []
  const evalStatusMessage = evalStatusMessageMap[indexType]
  const showScores = evalStatus === 'ready' || evalStatus === 'refreshing' || evalStatus === 'degraded'
  const displayResponse = showScores ? response : null
  const totalScore = displayResponse?.scores?.total
  const priceSeries = priceSeriesMap[indexType] ?? []

  const handleRetry = () => {
    setEvalStatusMap((prev) => ({
      ...prev,
      [indexType]: response ? 'refreshing' : 'loading',
    }))
    setIsEvalRetrying(false)
    void fetchAll()
  }

  const EVAL_RETRY_DELAYS_MS = [1500, 3000, 6000]

  const genRequestId = () => {
    try {
      return crypto.randomUUID()
    } catch {
      return `${Date.now()}-${Math.random().toString(16).slice(2)}`
    }
  }

  const resolveApiIndexType = (targetIndex: IndexType) => {
    if (targetIndex === 'sp500_jpy') return 'SP500_JPY'
    if (targetIndex === 'orukan_jpy') return 'ORUKAN_JPY'
    return targetIndex
  }

  const resolveUiStatus = (data: EvaluateResponse): EvalStatus => {
    const apiStatus = (data.status ?? 'ready') as EvalStatus
    const reasons = data.reasons ?? []
    if (apiStatus === 'error') return 'error'
    if (apiStatus === 'loading') return 'loading'

    // MA欠損だけで全体停止しない
    if (hasUsableScores(data)) return 'ready'

    // スコアが欠損している場合のみ degraded 扱い（計算中）
    if (reasons.includes('TECHNICAL_UNAVAILABLE') || reasons.includes('PRICE_HISTORY_EMPTY')) {
      return 'degraded'
    }
    return 'degraded'
  }

  const scheduleEvalRetry = (
    targetIndex: IndexType,
    payload: Partial<EvaluateRequest> | undefined,
    markPrimary: boolean,
    retryCount: number,
  ) => {
    if (retryCount >= EVAL_RETRY_DELAYS_MS.length) return
    if (evalRetryTimeoutRef.current) {
      clearTimeout(evalRetryTimeoutRef.current)
    }
    evalRetryTimeoutRef.current = setTimeout(() => {
      fetchEvaluation(targetIndex, payload, markPrimary, retryCount + 1)
    }, EVAL_RETRY_DELAYS_MS[retryCount])
  }

  const fetchEvaluation = async (
    targetIndex: IndexType,
    payload?: Partial<EvaluateRequest>,
    markPrimary = false,
    retryCount = 0,
  ) => {
    const reqSeq = ++evalReqSeqRef.current
    const clientRequestId = genRequestId()
    latestEvalRequestIdRef.current[targetIndex] = clientRequestId
    try {
      const apiIndexType = resolveApiIndexType(targetIndex)
      const body = { ...lastRequest, ...(payload ?? {}), index_type: apiIndexType, request_id: clientRequestId }
      if (markPrimary) {
        setError(null)
        if (retryCount === 0) {
          setEvalStatusMap((prev) => ({
            ...prev,
            [targetIndex]: response ? 'refreshing' : 'loading',
          }))
        }
      }
      const res = await apiClient.post<EvaluateResponse>('/api/evaluate', body)
      if (reqSeq !== evalReqSeqRef.current) return
      if (res.data.request_id !== latestEvalRequestIdRef.current[targetIndex]) return
      const latestSeries = priceSeriesMap[targetIndex] ?? []
      const normalized = normalizeEvaluateResponse(res.data, latestSeries)
      const status = resolveUiStatus(normalized)
      const reasons = normalized.reasons ?? []
      let uiMessage: string | undefined
      if (reasons.includes('TECHNICAL_UNAVAILABLE')) {
        uiMessage = 'MA200計算中（データ不足）'
      } else if (status === 'degraded') {
        if (!res.data.price_series || res.data.price_series.length === 0) {
          uiMessage = '価格履歴の取得が未完了のため、スコアは確定していません。'
        } else {
          uiMessage = '一部データ取得中のため、スコアは確定していません。'
        }
      }
      if (markPrimary) {
        setEvalStatusMap((prev) => ({ ...prev, [targetIndex]: status }))
        setEvalReasonsMap((prev) => ({ ...prev, [targetIndex]: reasons }))
        setEvalStatusMessageMap((prev) => ({ ...prev, [targetIndex]: uiMessage ?? '' }))
      }

      if (status === 'degraded') {
        setResponses((prev) => ({ ...prev, [targetIndex]: normalized }))
        if (!markPrimary) return
        if (retryCount >= EVAL_RETRY_DELAYS_MS.length) {
          setIsEvalRetrying(false)
          setEvalStatusMap((prev) => ({ ...prev, [targetIndex]: 'degraded' }))
          return
        }
        setIsEvalRetrying(true)
        console.warn('[EVAL DEGRADED]', {
          index: targetIndex,
          retryCount,
          reasons,
          status: normalized.status,
          scores: normalized.scores,
        })
        scheduleEvalRetry(targetIndex, payload, markPrimary, retryCount)
        return
      }

      if (status === 'error') {
        if (markPrimary) {
          setIsEvalRetrying(false)
          setError('評価データの取得に失敗しました。再取得してください。')
        }
        return
      }

      setResponses((prev) => ({ ...prev, [targetIndex]: normalized }))
      if (targetIndex === indexType && payload)
        setLastRequest((prev) => ({ ...prev, ...payload, index_type: targetIndex }))
      if (markPrimary) {
        setLastUpdated(new Date())
        setIsEvalRetrying(false)
        setEvalStatusMap((prev) => ({ ...prev, [targetIndex]: 'ready' }))
        setEvalReasonsMap((prev) => ({ ...prev, [targetIndex]: reasons }))
      }
    } catch (e: any) {
      if (reqSeq !== evalReqSeqRef.current) return
      const status = e?.response?.status
      if (markPrimary) {
        setIsEvalRetrying(false)
        setEvalStatusMap((prev) => ({ ...prev, [targetIndex]: 'error' }))
        setEvalReasonsMap((prev) => ({ ...prev, [targetIndex]: ['PRICE_HISTORY_UNAVAILABLE'] }))
        setEvalStatusMessageMap((prev) => ({
          ...prev,
          [targetIndex]: '価格履歴の取得に失敗しました。再取得してください。',
        }))
      }
      if (markPrimary) {
        setError(
          status === 502 || status === 503
            ? '価格履歴の取得に失敗しました。再取得してください。'
            : e.message,
        )
      } else {
        console.error('評価の取得に失敗しました', e)
      }
    }
  }

  const getPriceHistoryEndpoint = (targetIndex: IndexType) => {
    const map: Record<IndexType, string> = {
      SP500: '/api/sp500/price-history',
      sp500_jpy: '/api/sp500-jpy/price-history',
      TOPIX: '/api/topix/price-history',
      NIKKEI: '/api/nikkei/price-history',
      NIFTY50: '/api/nifty50/price-history',
      ORUKAN: '/api/orukan/price-history',
      orukan_jpy: '/api/orukan-jpy/price-history',
    }
    return map[targetIndex]
  }

  const fetchPriceSeries = async (targetIndex: IndexType) => {
    const reqSeq = ++priceReqSeqRef.current
    try {
      const res = await apiClient.get<PricePoint[]>(getPriceHistoryEndpoint(targetIndex))
      if (reqSeq !== priceReqSeqRef.current) return
      const sorted = [...res.data]
        .filter((p) => typeof p?.date === 'string' && typeof p?.close === 'number' && Number.isFinite(p?.close))
        .sort((a, b) => a.date.localeCompare(b.date))
        .map((p, idx) => {
          const row = {
            ...p,
            ma20: typeof p.ma20 === 'number' && Number.isFinite(p.ma20) ? p.ma20 : null,
            ma60: typeof p.ma60 === 'number' && Number.isFinite(p.ma60) ? p.ma60 : null,
            ma200: typeof p.ma200 === 'number' && Number.isFinite(p.ma200) ? p.ma200 : null,
          }
          if (idx === 0 || idx === res.data.length - 1) {
            console.debug('[PRICE ROW]', { index: targetIndex, row })
          }
          return row
        })
      setPriceSeriesMap((prev) => ({ ...prev, [targetIndex]: sorted }))
    } catch (e: any) {
      console.error('価格履歴取得に失敗しました', e)
    }
  }

  const fetchNavs = async () => {
    if (indexType !== 'SP500') {
      setSyntheticNav(null)
      setFundNav(null)
      return
    }
    try {
      const [syntheticRes, fundRes] = await Promise.all([
        apiClient.get<SyntheticNavResponse>('/api/nav/sp500-synthetic').catch(() => null),
        apiClient.get<FundNavResponse>('/api/nav/emaxis-slim-sp500').catch(() => null),
      ])
      setSyntheticNav(syntheticRes?.data ?? null)
      setFundNav(fundRes?.data ?? null)
    } catch (err) {
      console.error(err)
    }
  }

  const handleScoreMaChange = (value: number) => {
    setViewDays(value as ScoreMaDays)
  }

  const fetchAll = async () => {
    const targets: IndexType[] = (() => {
      if (indexType === 'ORUKAN' || indexType === 'orukan_jpy') return ['ORUKAN', 'orukan_jpy']
      if (indexType === 'sp500_jpy') return ['SP500', 'sp500_jpy']
      return [indexType]
    })()

    const primary = indexType
    const secondaryTargets = targets.filter((target) => target !== primary)

    await fetchPriceSeries(primary)
    await fetchEvaluation(primary, undefined, true)

    await Promise.all(
      secondaryTargets.flatMap((target) => [fetchEvaluation(target), fetchPriceSeries(target)]),
    )
    await fetchNavs()
  }

  useEffect(() => {
    void fetchAll()
    const id = setInterval(() => {
      void fetchAll()
    }, REFRESH_INTERVAL_MS)
    return () => clearInterval(id)
  }, [lastRequest, indexType])

  useEffect(() => {
    return () => {
      if (evalRetryTimeoutRef.current) {
        clearTimeout(evalRetryTimeoutRef.current)
      }
    }
  }, [])

  const lastUpdatedLabel = useMemo(() => {
    if (!lastUpdated) return '未更新'
    return lastUpdated.toLocaleTimeString('ja-JP', { hour: '2-digit', minute: '2-digit' })
  }, [lastUpdated])

  const highlights = useMemo(() => buildHighlights(displayResponse), [displayResponse])

  const zoneText = useMemo(() => getScoreZoneText(totalScore), [totalScore])

  const avatarDecision = useMemo(() => decideSellAction(totalScore), [totalScore])

  const { chartSeries, totalReturnLabels, legendLabels } = useMemo(
    () =>
      buildChartState({
        indexType,
        priceSeriesMap,
        startOption,
        customStart,
        priceDisplayMode,
      }),
    [indexType, priceSeriesMap, startOption, customStart, priceDisplayMode],
  )

  const forexInsight = useMemo(
    () => buildForexInsight(indexType, responses),
    [indexType, responses],
  )

  useEffect(() => {
    if (startOption === 'custom' && !customStart && priceSeries.length) {
      setCustomStart(priceSeries[0].date)
    }
  }, [startOption, customStart, priceSeries])

  // ★ 時間軸タブに合わせてチャート開始時点を同期（短期→1か月、中期→6か月、長期→1年）
  useEffect(() => {
    const rangeByViewDays: Record<ScoreMaDays, StartOption> = {
      20: '1m',
      60: '6m',
      200: '1y',
    }
    const next = rangeByViewDays[viewDays]
    setStartOption(next)
    setCustomStart('')
  }, [viewDays])

  // ★ 追加：価格データの「最新日付」を基準にイベントを取得
  useEffect(() => {
    if (!priceSeries.length) return

    const lastPoint = priceSeries[priceSeries.length - 1]
    const lastDateIso = lastPoint?.date
    if (!lastDateIso) return

    const run = async () => {
      try {
        setIsEventsLoading(true)
        setEventsError(null)

        const data = await fetchEvents(lastDateIso)
        setEvents(data)
        console.log('[EVENT TRACE]', data)
      } catch (e: any) {
        console.error('イベント取得に失敗しました', e)
        setEventsError(e.message ?? 'イベント取得に失敗しました')
      } finally {
        setIsEventsLoading(false)
      }
    }

    run()
  }, [indexType, priceSeries])

  const viewLabelMap: Record<ScoreMaDays, string> = {
    20: '短期目線',
    60: '中期目線',
    200: '長期目線',
  }
  const viewDescriptionMap: Record<ScoreMaDays, string[]> = {
    20: [
      '短期目線では、直近の値動きや過熱感、イベントの影響を重視します。',
      '「今すぐ動くべきか」「一時的な調整が入りそうか」といった直近のリスクを確認する視点です。',
      '短期的なノイズも多いため、ここでの判断はタイミング調整の意味合いが強くなります。',
    ],
    60: [
      '中期目線では、トレンドの持続性や環境の変化を重視します。',
      '短期のブレをならしながら、「流れとしてどうか？」を判断する視点です。',
      'この視点は、売り・保有・様子見の判断の中心になります。',
    ],
    200: [
      '長期目線では、過去の平均水準や構造的な割高・割安感を重視します。',
      '「今は歴史的に見てどの位置か？」という俯瞰の視点です。',
      'ここでの判断は、天井圏か、まだ余地があるかを確認する意味合いになります。',
    ],
  }
  const viewLabel = viewLabelMap[viewDays]
  const viewDescriptionLines = viewDescriptionMap[viewDays]
  const viewKeyMap: Record<ScoreMaDays, 'short' | 'mid' | 'long'> = {
    20: 'short',
    60: 'mid',
    200: 'long',
  }
  const viewKey = viewKeyMap[viewDays]
  const activeBreakdown = useMemo(() => getActiveBreakdown(viewKey, displayResponse), [viewKey, displayResponse])
  const breakdownTitleMap: Record<ViewKey, string> = {
    short: '短期目線の内訳',
    mid: '中期目線の内訳',
    long: '長期目線の内訳',
  }
  const breakdownFallbackNote = activeBreakdown?.isFallback
    ? '※内訳の時間軸別データが未提供のため、内訳は統合（総合）ベースで表示しています。'
    : undefined

  const reasonMessages = evalReasons
    .map((reason) => reasonLabelMap[reason] ?? reason)
    .filter((reason, index, array) => array.indexOf(reason) === index)
    .slice(0, 2)

  const degradedMessage =
    reasonMessages.length > 0
      ? `ℹ 状態：${reasonMessages.join(' / ')}`
      : 'ℹ 状態：MA200計算中（データ不足）'

  const statusMessage =
    evalStatus === 'error'
      ? error ?? '評価データの取得に失敗しました。'
      : evalStatusMessage || degradedMessage

  const timeAxisNote =
    '※ 総合スコア（統合判断）とは別指標です。ここでは、時間軸ごとの評価を参考値として確認できます。'
  const timeAxisCard = (
    <Card>
      <CardContent>
        <Typography variant="subtitle1" fontWeight={700} gutterBottom>
          時間軸別の評価（参考）
        </Typography>
        <Typography variant="body2" color="text.secondary">
          総合スコアは「今どうすべきか」の結論です。
          <br />
          ここでは、その判断の背景を時間軸ごとの評価として確認できます。
        </Typography>
        <Box mt={2}>
          <Tabs
            value={viewDays}
            onChange={(_, value) => handleScoreMaChange(Number(value))}
            variant="fullWidth"
            indicatorColor="primary"
            textColor="primary"
            TabIndicatorProps={{ sx: { height: 3 } }}
            sx={{
              borderBottom: (theme) => `1px solid ${theme.palette.divider}`,
              '& .MuiTab-root': {
                color: 'text.secondary',
                '&:hover': { color: 'text.primary' },
              },
              '& .MuiTab-root.Mui-selected': { color: 'primary.main' },
            }}
          >
            <Tab
              label={
                <HoverTooltip content={timeAxisNote} placement="top">
                  <span>短期目線</span>
                </HoverTooltip>
              }
              value={20}
            />
            <Tab
              label={
                <HoverTooltip content={timeAxisNote} placement="top">
                  <span>中期目線</span>
                </HoverTooltip>
              }
              value={60}
            />
            <Tab
              label={
                <HoverTooltip content={timeAxisNote} placement="top">
                  <span>長期目線</span>
                </HoverTooltip>
              }
              value={200}
            />
          </Tabs>
        </Box>
        <TimeAxisBreakdownSection
          title={breakdownTitleMap[viewKey]}
          fallbackNote={breakdownFallbackNote}
          scores={activeBreakdown?.scores}
          technical={activeBreakdown?.technical}
          macro={activeBreakdown?.macro}
          status={evalStatus}
          tooltips={tooltipTexts}
        />
        <Stack direction="row" alignItems="baseline" spacing={1} mt={2}>
          <Typography variant="subtitle2" fontWeight={700}>
            {`${viewLabel}スコア:`}
          </Typography>
          <Typography variant="h6" color="primary.main" fontWeight={700}>
            {displayResponse?.period_scores?.[viewKey] !== undefined
              ? displayResponse.period_scores[viewKey].toFixed(1)
              : displayResponse?.scores?.period_total !== undefined
                ? displayResponse.scores.period_total.toFixed(1)
                : '--'}
          </Typography>
        </Stack>
        <Stack spacing={1}>
          {viewDescriptionLines.map((line, index) => (
            <Typography key={`view-description-${index}`} variant="body2" color="text.secondary">
              {line}
            </Typography>
          ))}
        </Stack>
      </CardContent>
    </Card>
  )

  return (
    <Stack spacing={3}>
      <Box
        sx={{
          width: '100%',
          backgroundColor: (theme) => (theme.palette.mode === 'dark' ? '#2a2a2a' : '#f5f5f5'),
          color: (theme) => (theme.palette.mode === 'dark' ? '#ddd' : '#444'),
          fontSize: '12.5px',
          px: 2,
          py: 1,
        }}
      >
        <Typography variant="caption" sx={{ display: 'block', lineHeight: 1.5 }}>
          ⚠ 本サービスは投資助言ではありません。表示されるスコアは参考情報であり、最終的な投資判断はご自身の責任で行ってください。
          <br />
          <Box
            component="span"
            sx={{
              color: (theme) =>
                theme.palette.mode === 'dark'
                  ? 'rgba(221, 221, 221, 0.7)'
                  : 'rgba(68, 68, 68, 0.7)',
            }}
          >
            ※ ページ更新や条件切り替え時、最新データの取得・計算のため表示が反映されるまで数秒かかる場合があります。
          </Box>
        </Typography>
      </Box>

      <Box display="flex" justifyContent="space-between" alignItems="center" gap={1} flexWrap="wrap">
        <FormControl size="small" sx={{ minWidth: 200 }}>
          <InputLabel id="index-select-label">対象インデックス</InputLabel>
          <Select
            labelId="index-select-label"
            value={indexType}
            label="対象インデックス"
            onChange={(e) => setIndexType(e.target.value as IndexType)}
          >
            {(Object.keys(INDEX_LABELS) as IndexType[]).map((key) => (
              <MenuItem key={key} value={key}>
                {INDEX_LABELS[key]}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <Box display="flex" alignItems="center" gap={1}>
          <Chip label={`最終更新: ${lastUpdatedLabel}`} size="small" />
          {evalStatus === 'refreshing' && (
            <Typography variant="caption" color="text.secondary">
              更新中…
            </Typography>
          )}
          {evalStatus === 'degraded' && isEvalRetrying && (
            <Typography variant="caption" color="text.secondary">
              再取得中…
            </Typography>
          )}
          <Tooltip title="最新データを取得" arrow>
            <IconButton color="primary" onClick={() => void fetchAll()}>
              <RefreshIcon />
            </IconButton>
          </Tooltip>
        </Box>
      </Box>

      <AnimatePresence mode="wait">
        <motion.div key={displayMode} variants={motionVariants} initial="initial" animate="animate" exit="exit">
          <Grid container spacing={3} alignItems="stretch">
            {displayMode === 'simple' ? (
              <>
                <Grid item xs={12} md={7} sx={{ height: '100%' }}>
                  <Stack spacing={2} sx={{ height: '100%' }}>
                    <SimpleAlertCard
                      scores={displayResponse?.scores}
                      zoneText={zoneText}
                      onShowDetails={() => setShowDetails((prev) => !prev)}
                      expanded={showDetails}
                      tooltips={tooltipTexts}
                      status={evalStatus}
                      statusMessage={statusMessage}
                      onRetry={handleRetry}
                      isRetrying={isEvalRetrying}
                    />
                    {timeAxisCard}
                  </Stack>
                </Grid>

                <Grid item xs={12} md={5} sx={{ height: '100%' }}>
                  <SellTimingAvatarCard decision={avatarDecision} />
                </Grid>

                <Grid item xs={12}>
                  <Collapse in={showDetails}>
                    <ScoreSummaryCard
                      scores={displayResponse?.scores}
                      zoneText={zoneText}
                      onShowDetails={() => setShowDetails((prev) => !prev)}
                      expanded={showDetails}
                      tooltips={tooltipTexts}
                      status={evalStatus}
                      statusMessage={statusMessage}
                      onRetry={handleRetry}
                      isRetrying={isEvalRetrying}
                    />
                  </Collapse>
                </Grid>
              </>
            ) : (
              <>
                <Grid item xs={12} md={7} sx={{ height: '100%' }}>
                  <Stack spacing={2} sx={{ height: '100%' }}>
                    <ScoreSummaryCard
                      scores={displayResponse?.scores}
                      tooltips={tooltipTexts}
                      status={evalStatus}
                      statusMessage={statusMessage}
                      onRetry={handleRetry}
                      isRetrying={isEvalRetrying}
                    />
                    {timeAxisCard}
                  </Stack>
                </Grid>
                <Grid item xs={12} md={5} sx={{ height: '100%' }}>
                  <SellTimingAvatarCard decision={avatarDecision} />
                </Grid>
              </>
            )}
          </Grid>
        </motion.div>
      </AnimatePresence>

      {/* ★ かんたんモードではチャート自体を出さない（proのみ表示） */}
      {displayMode === 'pro' && (
        <Card>
          <CardContent>
            <Tooltip title={tooltipTexts.chart.title} arrow>
              <Typography variant="h6" gutterBottom component="div">
                {PRICE_TITLE_MAP[indexType]}
              </Typography>
            </Tooltip>
            {totalReturnLabels.length > 0 && (
              <Stack spacing={0.5} mb={2} mt={-0.5}>
                {totalReturnLabels.map((label) => (
                  <Typography key={label} variant="body2" color="text.secondary">
                    {label}
                  </Typography>
                ))}
              </Stack>
            )}
            <Box display="flex" alignItems="center" gap={2} flexWrap="wrap" mb={2}>
              <FormControl size="small" sx={{ minWidth: 180 }}>
                <InputLabel id="price-display-mode-label">表示モード</InputLabel>
                <Select
                  labelId="price-display-mode-label"
                  value={priceDisplayMode}
                  label="表示モード"
                  onChange={(e) => setPriceDisplayMode(e.target.value as PriceDisplayMode)}
                >
                  <MenuItem value="normalized">正規化</MenuItem>
                  <MenuItem value="actual">実価格</MenuItem>
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 200 }}>
                <InputLabel id="start-select-label">開始時点</InputLabel>
                <Select
                  labelId="start-select-label"
                  value={startOption}
                  label="開始時点"
                  onChange={(e) => setStartOption(e.target.value as StartOption)}
                >
                  <MenuItem value="max">全期間</MenuItem>
                  <MenuItem value="1m">1か月</MenuItem>
                  <MenuItem value="3m">3ヶ月前</MenuItem>
                  <MenuItem value="6m">6か月</MenuItem>
                  <MenuItem value="1y">1年</MenuItem>
                  <MenuItem value="3y">3年前</MenuItem>
                  <MenuItem value="5y">5年前</MenuItem>
                  <MenuItem value="custom">日付を指定</MenuItem>
                </Select>
              </FormControl>
              <TextField
                label="開始日を指定"
                type="date"
                size="small"
                value={customStart}
                onChange={(e) => setCustomStart(e.target.value)}
                disabled={startOption !== 'custom'}
                InputLabelProps={{ shrink: true }}
              />
            </Box>
            <AnimatePresence mode="wait">
              <motion.div
                key={`${startOption}-${customStart}-${displayMode}-${priceDisplayMode}`}
                variants={chartMotion}
                initial="initial"
                animate="animate"
                exit="exit"
              >
                {evalStatus === 'ready' || evalStatus === 'refreshing' ? (
                  <PriceChart
                    priceSeries={chartSeries}
                    simple={false} // proのみ描画なので実質false（互換維持）
                    tooltips={tooltipTexts}
                    legendLabels={legendLabels}
                  />
                ) : (
                  <Skeleton variant="rounded" height={260} />
                )}
              </motion.div>
            </AnimatePresence>
          </CardContent>
        </Card>
      )}

      {forexInsight && (
        <Card>
          <CardContent>
            <Typography variant="subtitle1" gutterBottom>
              為替インサイト
            </Typography>
            <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap">
              <Chip label={`スコア差: ${forexInsight.diff.toFixed(1)}pt`} color="info" size="small" />
              <Typography variant="body2" color="text.secondary">
                {forexInsight.message}
              </Typography>
            </Stack>
          </CardContent>
        </Card>
      )}

      <Grid container spacing={3}>
        <Grid item xs={12} md={7}>
          <MacroCards macroDetails={displayResponse?.macro_details} tooltips={tooltipTexts} />
        </Grid>
        <Grid item xs={12} md={5}>
          {/* ★ イベント一覧：旧 event_details に加えて /api/events の結果も渡す */}
          <EventList
            eventDetails={displayResponse?.event_details}
            events={events}
            isLoading={isEventsLoading}
            error={eventsError}
            tooltips={tooltipTexts}
          />
        </Grid>
      </Grid>

      {displayMode === 'pro' && (
        <>
          <Box position="fixed" bottom={24} right={24} zIndex={(theme) => theme.zIndex.tooltip}>
            <Tooltip title="あなたのポジションで試算（任意）" arrow>
              <Button variant="contained" color="secondary" onClick={() => setPositionDialogOpen(true)}>
                マイポジ試算（任意）
              </Button>
            </Tooltip>
          </Box>

          <Dialog open={positionDialogOpen} onClose={() => setPositionDialogOpen(false)} maxWidth="sm" fullWidth>
            <DialogTitle>マイポジ試算</DialogTitle>
            <DialogContent dividers>
              <PositionForm
                onSubmit={(req) => {
                  fetchEvaluation(indexType, req, true)
                  setPositionDialogOpen(false)
                }}
                marketValue={displayResponse?.market_value}
                pnl={displayResponse?.unrealized_pnl}
                syntheticNav={syntheticNav}
                fundNav={fundNav}
                tooltips={tooltipTexts}
              />
            </DialogContent>
            <DialogActions>
              <Button onClick={() => setPositionDialogOpen(false)}>閉じる</Button>
            </DialogActions>
          </Dialog>
        </>
      )}
    </Stack>
  )
}


function TimeAxisBreakdownSection({
  title,
  fallbackNote,
  scores,
  technical,
  macro,
  status,
  tooltips,
}: {
  title: string
  fallbackNote?: string
  scores?: { technical?: number; macro?: number; event_adjustment?: number }
  technical?: { d?: number; T_base?: number; T_trend?: number }
  macro?: { M?: number; macro_M?: number }
  status: EvalStatus
  tooltips: ReturnType<typeof buildTooltips>
}) {
  const showConfirmed = status === 'ready' || status === 'refreshing'

  return (
    <Box
      sx={{
        mt: 2,
        p: 1.5,
        borderRadius: 2,
        border: (theme) => `1px solid ${theme.palette.divider}`,
        bgcolor: (theme) => (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.02)' : 'rgba(0,0,0,0.02)'),
      }}
    >
      <Typography variant="subtitle2" fontWeight={700} gutterBottom>
        {title}
      </Typography>
      {fallbackNote && (
        <Typography variant="caption" color="text.secondary" display="block" mb={1}>
          {fallbackNote}
        </Typography>
      )}

      <Stack spacing={1}>
        <BreakdownBar
          label="テクニカル"
          value={showConfirmed ? scores?.technical : undefined}
          color="primary"
          tooltip={tooltips.score.technical}
        />
        <BreakdownBar
          label="マクロ"
          value={showConfirmed ? scores?.macro : undefined}
          color="secondary"
          tooltip={tooltips.score.macro}
        />
        <BreakdownBar
          label="イベント補正"
          value={showConfirmed ? scores?.event_adjustment : undefined}
          color="error"
          tooltip={tooltips.score.event}
        />
      </Stack>

      <Box display="grid" gridTemplateColumns="repeat(2, 1fr)" gap={1} mt={1.25}>
        <MetricItem label="乖離率 d" tooltip={tooltips.score.d} value={showConfirmed ? `${technical?.d ?? '--'}%` : '--'} />
        <MetricItem label="T_base" tooltip={tooltips.score.T_base} value={showConfirmed ? (technical?.T_base ?? '--') : '--'} />
        <MetricItem label="T_trend" tooltip={tooltips.score.T_trend} value={showConfirmed ? (technical?.T_trend ?? '--') : '--'} />
        <MetricItem label="マクロ M" tooltip={tooltips.score.macroM} value={showConfirmed ? (macro?.M ?? macro?.macro_M ?? '--') : '--'} />
      </Box>
    </Box>
  )
}

function BreakdownBar({
  label,
  value,
  color,
  tooltip,
}: {
  label: string
  value?: number
  color: 'primary' | 'secondary' | 'error'
  tooltip: string
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

function MetricItem({ label, tooltip, value }: { label: string; tooltip: string; value: string | number }) {
  return (
    <Box
      sx={{
        p: 1,
        borderRadius: 1,
        bgcolor: (theme) => (theme.palette.mode === 'dark' ? 'rgba(255,255,255,0.03)' : 'rgba(0,0,0,0.03)'),
      }}
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

type ChartPoint = PricePoint & { closeUsd?: number }

type LegendLabels = {
  close?: string
  closeUsd?: string
  ma20?: string
  ma60?: string
  ma200?: string
}

type ChartStateParams = {
  indexType: IndexType
  priceSeriesMap: Partial<Record<IndexType, PricePoint[]>>
  startOption: StartOption
  customStart: string
  priceDisplayMode: PriceDisplayMode
}

function buildChartState({
  indexType,
  priceSeriesMap,
  startOption,
  customStart,
  priceDisplayMode,
}: ChartStateParams): { chartSeries: ChartPoint[]; totalReturnLabels: string[]; legendLabels?: LegendLabels } {
  const primaryRaw = priceSeriesMap[indexType] ?? []
  const startDate = resolveStartDate(primaryRaw, startOption, customStart)
  const primaryFiltered = filterSeriesFromStart(primaryRaw, startDate)
  const durationLabel = getDurationLabel(startOption, customStart)
  const normalizedPrimary = normalizePriceSeries(primaryFiltered)
  const baseSeries = priceDisplayMode === 'normalized' ? normalizedPrimary : primaryFiltered

  if (isFxConvertedIndex(indexType)) {
    const baseIndex = getBaseIndex(indexType)
    const secondaryRaw = baseIndex ? priceSeriesMap[baseIndex] ?? [] : []
    const secondaryFiltered = filterSeriesFromStart(secondaryRaw, startDate)
    const normalizedSecondary = normalizePriceSeries(secondaryFiltered)
    const useUsdLine = priceDisplayMode === 'normalized'
    const chartSeries = useUsdLine
      ? buildDualSeries(normalizedPrimary, normalizedSecondary)
      : baseSeries

    return {
      chartSeries,
      totalReturnLabels: buildReturnLabels({
        indexType,
        primarySeries: primaryFiltered,
        secondarySeries: secondaryFiltered,
        durationLabel,
      }),
      legendLabels: useUsdLine
        ? {
            close: '円建て（終値）',
            closeUsd: 'ドル建て（終値）',
            ma20: 'MA20',
            ma60: 'MA60',
            ma200: 'MA200',
          }
        : undefined,
    }
  }

  return {
    chartSeries: baseSeries,
    totalReturnLabels: buildReturnLabels({ indexType, primarySeries: primaryFiltered, durationLabel }),
  }
}

function filterSeriesFromStart(series: PricePoint[], startDate: dayjs.Dayjs | null): PricePoint[] {
  if (!series.length || !startDate) return series
  return series.filter((p) => {
    const current = dayjs(p.date)
    return current.isAfter(startDate) || current.isSame(startDate, 'day')
  })
}

function normalizePriceSeries(series: PricePoint[]): PricePoint[] {
  if (!series.length) return []
  const basePrice = series[0].close
  if (basePrice === 0) return series
  const factor = 100 / basePrice
  return series.map((p) => ({
    ...p,
    close: roundToTwo(p.close * factor),
    ma20: p.ma20 !== null ? roundToTwo(p.ma20 * factor) : null,
    ma60: p.ma60 !== null ? roundToTwo(p.ma60 * factor) : null,
    ma200: p.ma200 !== null ? roundToTwo(p.ma200 * factor) : null,
  }))
}

function buildDualSeries(primary: PricePoint[], secondary: PricePoint[]): ChartPoint[] {
  const secondaryMap = new Map(secondary.map((p) => [p.date, p.close]))
  return primary
    .filter((p) => secondaryMap.has(p.date))
    .map((p) => ({
      ...p,
      closeUsd: roundToTwo(secondaryMap.get(p.date) ?? 0),
    }))
}

function resolveStartDate(series: PricePoint[], startOption: StartOption, customStart: string) {
  if (!series.length) return null
  const lastDate = dayjs(series[series.length - 1].date)

  switch (startOption) {
    case '1m':
      return lastDate.subtract(30, 'day')
    case '3m':
      return lastDate.subtract(90, 'day')
    case '6m':
      return lastDate.subtract(180, 'day')
    case '1y':
      return lastDate.subtract(365, 'day')
    case '3y':
      return lastDate.subtract(3 * 365, 'day')
    case '5y':
      return lastDate.subtract(5 * 365, 'day')
    case 'custom': {
      const parsed = dayjs(customStart)
      if (parsed.isValid()) return parsed
      return dayjs(series[0].date)
    }
    case 'max':
    default:
      return dayjs(series[0].date)
  }
}

function calculatePeriodReturn(series: PricePoint[]): number | null {
  if (!series.length) return null
  const first = series[0].close
  const last = series[series.length - 1].close
  if (first === 0) return null
  return (last / first - 1) * 100
}

function formatPercentage(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(1)}%`
}

function getDurationLabel(startOption: StartOption, customStart: string): string {
  const map: Record<StartOption, string> = {
    '1m': '1ヶ月トータル',
    '3m': '3ヶ月トータル',
    '6m': '6ヶ月トータル',
    '1y': '1年トータル',
    '3y': '3年トータル',
    '5y': '5年トータル',
    max: '全期間トータル',
    custom: '開始日からのトータル',
  }
  if (startOption === 'custom' && dayjs(customStart).isValid()) {
    return '開始日からのトータル'
  }
  return map[startOption]
}

function buildReturnLabels({
  indexType,
  primarySeries,
  secondarySeries,
  durationLabel,
}: {
  indexType: IndexType
  primarySeries: PricePoint[]
  secondarySeries?: PricePoint[]
  durationLabel: string
}): string[] {
  const labels: string[] = []

  if (isFxConvertedIndex(indexType)) {
    const usdReturn = calculatePeriodReturn(secondarySeries ?? [])
    const jpyReturn = calculatePeriodReturn(primarySeries)
    if (usdReturn !== null) labels.push(`ドル建て：${durationLabel} ${formatPercentage(usdReturn)}`)
    if (jpyReturn !== null) labels.push(`円建て  ：${durationLabel} ${formatPercentage(jpyReturn)}`)
    return labels
  }

  const ret = calculatePeriodReturn(primarySeries)
  if (ret !== null) labels.push(`${getCurrencyLabel(indexType)} ：${durationLabel} ${formatPercentage(ret)}`)
  return labels
}

function getCurrencyLabel(indexType: IndexType): 'ドル建て' | '円建て' {
  if (indexType === 'TOPIX' || indexType === 'NIKKEI' || indexType === 'orukan_jpy' || indexType === 'sp500_jpy')
    return '円建て'
  return 'ドル建て'
}

function buildForexInsight(
  indexType: IndexType,
  responses: Partial<Record<IndexType, EvaluateResponse>>,
): { diff: number; message: string } | null {
  const forexTargets: Partial<Record<IndexType, [IndexType, IndexType]>> = {
    ORUKAN: ['ORUKAN', 'orukan_jpy'],
    orukan_jpy: ['ORUKAN', 'orukan_jpy'],
    sp500_jpy: ['SP500', 'sp500_jpy'],
    SP500: ['SP500', 'sp500_jpy'],
  }

  const pair = forexTargets[indexType]
  if (!pair) return null

  const usd = responses[pair[0]]
  const jpy = responses[pair[1]]
  if (!usd || !jpy) return null

  const usdScore = usd.scores?.total ?? 0
  const jpyScore = jpy.scores?.total ?? 0
  const diff = jpyScore - usdScore

  if (diff > 5) {
    return {
      diff,
      message: '為替の影響で上振れしています。円安が進んだため、円建て評価額が押し上げられています。',
    }
  }
  if (diff < -5) {
    return {
      diff,
      message: '株価は上昇していますが、円高により円建てでは利益が削られています。為替による下押しが発生しています。',
    }
  }
  return {
    diff,
    message: 'ドル建てと円建ての動きはほぼ一致しています。為替の影響は小さく、中立的です。',
  }
}

function isFxConvertedIndex(indexType: IndexType): boolean {
  return indexType === 'orukan_jpy' || indexType === 'sp500_jpy'
}

function getBaseIndex(indexType: IndexType): IndexType | null {
  if (indexType === 'orukan_jpy') return 'ORUKAN'
  if (indexType === 'sp500_jpy') return 'SP500'
  return null
}

function roundToTwo(value: number): number {
  return Math.round(value * 100) / 100
}

function buildHighlights(response: EvaluateResponse | null): { icon: string; text: string }[] {
  if (!response) return []
  const highlights: { icon: string; text: string }[] = []
  const { technical_details: technical, macro_details: macro, event_details: event } = response

  if (technical?.d !== undefined) {
    if (technical.d >= 15) {
      highlights.push({ icon: '📈', text: '株価は長期平均よりかなり高い位置にあります。' })
    } else if (technical.d >= 5) {
      highlights.push({ icon: '📈', text: '株価は長期平均よりやや高い位置にあります。' })
    } else if (technical.d <= -5) {
      highlights.push({ icon: '📉', text: '株価は長期平均より低めの位置にあります。' })
    } else {
      highlights.push({ icon: '➖', text: '株価は長期平均に近い水準にあります。' })
    }
  }

  if (macro?.M !== undefined) {
    if (macro.M >= 70) {
      highlights.push({ icon: '💹', text: '金利やインフレなどの環境は、株式にとってやや逆風です。' })
    } else if (macro.M >= 50) {
      highlights.push({ icon: '💹', text: 'マクロ環境はやや注意が必要な水準です。' })
    } else {
      highlights.push({ icon: '🌤️', text: 'マクロ環境は比較的落ち着いています。' })
    }
  }

  if (event?.effective_event && event.E_adj !== 0) {
    highlights.push({
      icon: '⏰',
      text: `今週は「${event.effective_event.name}」が予定されており、発表前後は値動きが大きくなる可能性があります。`,
    })
  } else {
    highlights.push({ icon: '📆', text: '直近で特別に大きなイベントは予定されていません。' })
  }

  return highlights.slice(0, 4)
}

export default DashboardPage
