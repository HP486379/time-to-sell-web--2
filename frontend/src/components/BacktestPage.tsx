import { useState } from 'react'
import {
  Card,
  CardContent,
  CardHeader,
  Container,
  Grid,
  Stack,
  TextField,
  Button,
  Typography,
  Alert,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Divider,
} from '@mui/material'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import dayjs from 'dayjs'
import { runAccumulationBacktest, runBacktest } from '../apis'
import type { AccumulationBacktestRequest, BacktestRequest, BacktestResult } from '../types/apis'
import { INDEX_LABELS, type IndexType } from '../types/index'
import { getBacktestViewStatus, toBacktestIndexType } from '../utils/indexTypeMap'
import { getTranslations, type AppLanguage } from '../i18n'

const BACKTEST_START_DATES: Record<IndexType, string> = {
  SP500: '2000-01-01',
  sp500_jpy: '2000-01-01',
  TOPIX: '2008-01-04',
  NIKKEI: '2000-01-01',
  NIFTY50: '2007-09-17',
  ORUKAN: '2008-03-28',
  orukan_jpy: '2008-03-28',
}

const FULL_2005_INDEX_TYPES: IndexType[] = ['SP500', 'sp500_jpy', 'NIKKEI']
const DEFAULT_LONG_PRECOMPUTED_START_DATES = ['2010-01-01', '2014-01-01', '2015-01-01']
const PRECOMPUTED_END_DATE = '2025-12-31'
const RUNTIME_MAX_DAYS = 366 * 3
const PRECOMPUTED_INITIAL_CASH = 1_000_000
const PRECOMPUTED_SELL_THRESHOLD = 80
const PRECOMPUTED_BUY_THRESHOLD = 40
const PRECOMPUTED_SCORE_MA = 200
const ACCUMULATION_DEFAULT_START_DATE = '2023-01-01'
const ACCUMULATION_DEFAULT_INITIAL_CASH = 0
const ACCUMULATION_DEFAULT_MONTHLY_AMOUNT = 30_000
const ACCUMULATION_DEFAULT_PROFIT_TAKE_PCT = 20

type BacktestMode = 'lump_sum' | 'accumulation'

const getPrecomputedStartDates = (indexType: IndexType): string[] => {
  const fixedStarts = FULL_2005_INDEX_TYPES.includes(indexType)
    ? ['2005-01-01', ...DEFAULT_LONG_PRECOMPUTED_START_DATES]
    : DEFAULT_LONG_PRECOMPUTED_START_DATES
  return Array.from(new Set([BACKTEST_START_DATES[indexType], ...fixedStarts])).sort()
}

const isRuntimeRangeAllowed = (startDate: string, endDate: string): boolean => {
  const start = dayjs(startDate)
  const end = dayjs(endDate)
  if (!start.isValid() || !end.isValid() || end.isBefore(start)) return false
  return end.diff(start, 'day') <= RUNTIME_MAX_DAYS
}

const isPrecomputedRequest = (request: BacktestRequest): boolean => {
  return (
    getPrecomputedStartDates(request.index_type as IndexType).includes(request.start_date) &&
    request.end_date === PRECOMPUTED_END_DATE &&
    Number(request.initial_cash) === PRECOMPUTED_INITIAL_CASH &&
    Number(request.sell_threshold) === PRECOMPUTED_SELL_THRESHOLD &&
    Number(request.buy_threshold) === PRECOMPUTED_BUY_THRESHOLD &&
    Number(request.score_ma) === PRECOMPUTED_SCORE_MA
  )
}

const getBacktestValidationError = (mode: BacktestMode, request: BacktestRequest, language: AppLanguage): string | null => {
  if (mode === 'accumulation') {
    if (isRuntimeRangeAllowed(request.start_date, request.end_date)) return null
    return language === 'en'
      ? 'Custom DCA backtests are limited to 3 years. Longer DCA presets will be supported later.'
      : '積立バックテストの任意計算は3年以内のみ対応です。長期の積立検証は今後の事前計算プリセットで対応予定です。'
  }

  if (isPrecomputedRequest(request)) return null
  if (isRuntimeRangeAllowed(request.start_date, request.end_date)) return null

  const availableStarts = getPrecomputedStartDates(request.index_type as IndexType).join(' / ')
  return language === 'en'
    ? `Backtests longer than 3 years are available only for precomputed presets. Use start ${availableStarts}, end ${PRECOMPUTED_END_DATE}, initial cash ¥1,000,000, sell 80, buy 40, and MA200.`
    : `3年超のバックテストは事前計算済み期間のみ利用できます。対象インデックスの開始日は ${availableStarts}、終了日は ${PRECOMPUTED_END_DATE}、初期資金100万円・売り80・買い40・MA200にしてください。`
}

const DEFAULT_INDEX_TYPE: IndexType = 'SP500'

const DEFAULT_REQUEST: BacktestRequest = {
  start_date: BACKTEST_START_DATES[DEFAULT_INDEX_TYPE],
  end_date: PRECOMPUTED_END_DATE,
  initial_cash: PRECOMPUTED_INITIAL_CASH,
  sell_threshold: PRECOMPUTED_SELL_THRESHOLD,
  buy_threshold: PRECOMPUTED_BUY_THRESHOLD,
  index_type: DEFAULT_INDEX_TYPE,
  score_ma: PRECOMPUTED_SCORE_MA,
}

const currencyFmt = new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 })
const pctFmt = (v: unknown) => {
  const num = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(num) ? `${num.toFixed(2)} %` : '-'
}
const currencySafe = (v: unknown) => {
  const num = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(num) ? currencyFmt.format(num) : '-'
}
const numSafe = (v: unknown) => {
  const num = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(num) ? num.toFixed(2) : '-'
}
const labelNumberSafe = (v: unknown, fallback: number) => {
  const num = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(num) ? num : fallback
}

export function BacktestPage({ language = 'ja' }: { language?: AppLanguage }) {
  const t = getTranslations(language).backtest
  const [mode, setMode] = useState<BacktestMode>('lump_sum')
  const [params, setParams] = useState<BacktestRequest>(DEFAULT_REQUEST)
  const [monthlyAmount, setMonthlyAmount] = useState(ACCUMULATION_DEFAULT_MONTHLY_AMOUNT)
  const [profitTakePct, setProfitTakePct] = useState(ACCUMULATION_DEFAULT_PROFIT_TAKE_PCT)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleModeChange = (nextMode: BacktestMode) => {
    setMode(nextMode)
    setResult(null)
    setError(null)
    if (nextMode === 'accumulation') {
      setParams((prev) => ({
        ...prev,
        start_date: ACCUMULATION_DEFAULT_START_DATE,
        end_date: PRECOMPUTED_END_DATE,
        initial_cash: ACCUMULATION_DEFAULT_INITIAL_CASH,
        sell_threshold: PRECOMPUTED_SELL_THRESHOLD,
        buy_threshold: PRECOMPUTED_BUY_THRESHOLD,
        score_ma: PRECOMPUTED_SCORE_MA,
      }))
    } else {
      setParams((prev) => ({
        ...prev,
        start_date: BACKTEST_START_DATES[prev.index_type as IndexType],
        end_date: PRECOMPUTED_END_DATE,
        initial_cash: PRECOMPUTED_INITIAL_CASH,
        sell_threshold: PRECOMPUTED_SELL_THRESHOLD,
        buy_threshold: PRECOMPUTED_BUY_THRESHOLD,
        score_ma: PRECOMPUTED_SCORE_MA,
      }))
    }
  }

  const handleChange = (key: keyof BacktestRequest, value: string | number) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const handleIndexChange = (indexType: IndexType) => {
    setParams((prev) => ({
      ...prev,
      index_type: indexType,
      start_date: mode === 'accumulation' ? ACCUMULATION_DEFAULT_START_DATE : BACKTEST_START_DATES[indexType],
      end_date: PRECOMPUTED_END_DATE,
      initial_cash: mode === 'accumulation' ? ACCUMULATION_DEFAULT_INITIAL_CASH : PRECOMPUTED_INITIAL_CASH,
      sell_threshold: PRECOMPUTED_SELL_THRESHOLD,
      buy_threshold: PRECOMPUTED_BUY_THRESHOLD,
      score_ma: PRECOMPUTED_SCORE_MA,
    }))
    setResult(null)
    setError(null)
  }

  const handleRun = async () => {
    const validationError = getBacktestValidationError(mode, params, language)
    if (validationError) {
      setError(validationError)
      setResult(null)
      return
    }

    try {
      setLoading(true)
      setError(null)
      const normalizedParams = { ...params, index_type: toBacktestIndexType(params.index_type as IndexType) }
      const res =
        mode === 'accumulation'
          ? await runAccumulationBacktest({
              ...normalizedParams,
              monthly_amount: monthlyAmount,
              profit_take_pct: profitTakePct,
            } as AccumulationBacktestRequest)
          : await runBacktest(normalizedParams)
      setResult(res)
    } catch (e: any) {
      setError(e.message ?? (language === 'en' ? 'Backtest failed' : 'バックテストに失敗しました'))
    } finally {
      setLoading(false)
    }
  }

  const chartData =
    mode === 'accumulation'
      ? (result?.portfolio_history || []).map((point, idx) => ({
          date: point.date,
          strategy: point.value,
          hold: result?.buy_hold_history?.[idx]?.value ?? null,
        }))
      : (result?.equity_curve || []).map((point) => ({
          date: point.date,
          close: point.close,
          ma20: point.ma20 ?? null,
          ma60: point.ma60 ?? null,
          ma200: point.ma200 ?? null,
        }))

  const startDateHelperText =
    mode === 'accumulation'
      ? language === 'en'
        ? 'Custom DCA backtests are limited to 3 years'
        : '積立バックテストの任意計算は3年以内のみ対応'
      : language === 'en'
        ? `Longer than 3 years: ${getPrecomputedStartDates(params.index_type as IndexType).join(' / ')} only`
        : `3年超は ${getPrecomputedStartDates(params.index_type as IndexType).join(' / ')} のみ対応`

  const scoreSamples = result?.diagnostics?.score_samples
  const accumulationDiagnostics = result?.diagnostics?.accumulation_diagnostics
  const topScoreDates = accumulationDiagnostics?.top_score_dates ?? []
  const sellThresholdLabel = labelNumberSafe(result?.diagnostics?.sell_threshold, labelNumberSafe(params.sell_threshold, PRECOMPUTED_SELL_THRESHOLD))
  const nearSellThresholdLabel = labelNumberSafe(scoreSamples?.near_sell_threshold, Math.max(sellThresholdLabel - 5, 0))
  const buyThresholdLabel = labelNumberSafe(result?.diagnostics?.buy_threshold, labelNumberSafe(params.buy_threshold, PRECOMPUTED_BUY_THRESHOLD))
  const daysSuffix = language === 'en' ? 'days' : '日'
  const timesSuffix = language === 'en' ? 'times' : '回'

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Typography variant="h4" fontWeight={700} color="primary.light">
          {t.title}
        </Typography>
        <Card>
          <CardHeader title={t.parameters} />
          <CardContent>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="mode-select">{t.type}</InputLabel>
                  <Select labelId="mode-select" value={mode} label={t.type} onChange={(e) => handleModeChange(e.target.value as BacktestMode)}>
                    <MenuItem value="lump_sum">{t.lumpSum}</MenuItem>
                    <MenuItem value="accumulation">{t.accumulation}</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField label={t.startDate} type="date" fullWidth value={params.start_date} onChange={(e) => handleChange('start_date', e.target.value)} InputLabelProps={{ shrink: true }} helperText={startDateHelperText} />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField label={t.endDate} type="date" fullWidth value={params.end_date} onChange={(e) => handleChange('end_date', e.target.value)} InputLabelProps={{ shrink: true }} />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField label={t.initialCash} type="number" fullWidth value={params.initial_cash} onChange={(e) => handleChange('initial_cash', Number(e.target.value))} />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="index-select">{t.targetIndex}</InputLabel>
                  <Select labelId="index-select" value={params.index_type} label={t.targetIndex} onChange={(e) => handleIndexChange(e.target.value as IndexType)}>
                    {(Object.keys(INDEX_LABELS) as IndexType[]).map((key) => (
                      <MenuItem key={key} value={key}>{INDEX_LABELS[key]}</MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              {mode === 'accumulation' && (
                <>
                  <Grid item xs={12} sm={6} md={3}>
                    <TextField label={t.monthlyAmount} type="number" fullWidth value={monthlyAmount} onChange={(e) => setMonthlyAmount(Number(e.target.value))} />
                  </Grid>
                  <Grid item xs={12} sm={6} md={3}>
                    <TextField label={t.profitTakePct} type="number" fullWidth value={profitTakePct} onChange={(e) => setProfitTakePct(Number(e.target.value))} helperText={t.profitTakePctHelp} />
                  </Grid>
                </>
              )}
              <Grid item xs={12} sm={6} md={3}>
                <TextField label={t.sellThreshold} type="number" fullWidth value={params.sell_threshold} onChange={(e) => handleChange('sell_threshold', Number(e.target.value))} helperText={mode === 'accumulation' ? t.sellThresholdHelp : undefined} />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField label={t.buyThreshold} type="number" fullWidth value={params.buy_threshold} onChange={(e) => handleChange('buy_threshold', Number(e.target.value))} helperText={mode === 'accumulation' ? t.buyThresholdHelp : undefined} />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="score-ma-select">{t.scoreMa}</InputLabel>
                  <Select labelId="score-ma-select" value={params.score_ma} label={t.scoreMa} onChange={(e) => handleChange('score_ma', Number(e.target.value))}>
                    <MenuItem value={20}>{t.ma20}</MenuItem>
                    <MenuItem value={60}>{t.ma60}</MenuItem>
                    <MenuItem value={200}>{t.ma200}</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12}>
                <Button variant="contained" onClick={handleRun} disabled={loading}>{loading ? t.running : t.run}</Button>
              </Grid>
            </Grid>
          </CardContent>
        </Card>

        <Card>
          <CardHeader title={t.result} subheader={result ? `${params.start_date}〜${params.end_date}` : undefined} />
          <CardContent>
            {result ? (
              <Stack spacing={0.5}>
                <Typography variant="body2">{t.finalAsset}: <strong>{currencySafe(result.summary.final_equity)}</strong></Typography>
                <Typography variant="body2">{mode === 'accumulation' ? t.regularDcaHold : t.buyAndHold}: <strong>{currencySafe(result.summary.hold_equity)}</strong></Typography>
                {mode === 'accumulation' && (
                  <>
                    <Typography variant="body2">{t.totalContributed}: <strong>{currencySafe(result.summary.total_contributed)}</strong></Typography>
                    <Typography variant="body2">{t.waitingCash}: <strong>{currencySafe(result.summary.waiting_cash)}</strong></Typography>
                    <Typography variant="body2">{t.deferredAndReinvest}: <strong>{result.summary.deferred_contribution_count ?? 0} {timesSuffix} / {result.summary.reinvest_count ?? 0} {timesSuffix}</strong></Typography>
                    <Typography variant="body2">{t.deferredAmount}: <strong>{currencySafe(result.summary.deferred_contribution_amount)}</strong></Typography>
                  </>
                )}
                <Typography variant="body2">{t.totalReturn}: <strong>{pctFmt(result.summary.total_return)}</strong></Typography>
                {mode === 'accumulation' && result.summary.hold_return !== undefined && (
                  <Typography variant="body2">{t.regularDcaReturn}: <strong>{pctFmt(result.summary.hold_return)}</strong></Typography>
                )}
                <Typography variant="body2">{t.maxDrawdown}: <strong>{pctFmt(result.summary.max_drawdown)}</strong></Typography>
                <Typography variant="body2">{t.tradeCount}: <strong>{result.summary.trade_count ?? '-'} {timesSuffix}</strong></Typography>
                {mode === 'lump_sum' && getBacktestViewStatus(result.summary.trade_count) && (
                  <Typography variant="body2" color="text.secondary">{getBacktestViewStatus(result.summary.trade_count)}</Typography>
                )}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">{t.emptyPrompt}</Typography>
            )}
          </CardContent>
        </Card>

        {mode === 'accumulation' && result && (
          <Card>
            <CardHeader title={t.diagnostics} subheader={t.diagnosticsSub} />
            <CardContent>
              <Stack spacing={1.2}>
                <Grid container spacing={2}>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{t.maxScore}: <strong>{numSafe(scoreSamples?.max_score)}</strong></Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{sellThresholdLabel}{t.aboveDays}: <strong>{scoreSamples?.days_score_above_sell_threshold ?? 0} {daysSuffix}</strong></Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{nearSellThresholdLabel}{t.aboveDays}: <strong>{scoreSamples?.days_score_above_near_sell_threshold ?? 0} {daysSuffix}</strong></Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{buyThresholdLabel}{t.belowDays}: <strong>{scoreSamples?.days_score_below_buy_threshold ?? 0} {daysSuffix}</strong></Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{t.deferredCount}: <strong>{accumulationDiagnostics?.deferred_contribution_count ?? 0} {timesSuffix}</strong></Typography></Grid>
                  <Grid item xs={12} sm={6} md={3}><Typography variant="body2">{t.deferredContributionAmount}: <strong>{currencySafe(accumulationDiagnostics?.deferred_contribution_amount)}</strong></Typography></Grid>
                </Grid>
                {result.diagnostics?.index_specific_sell_adjustment_note && <Alert severity="info">{result.diagnostics.index_specific_sell_adjustment_note}</Alert>}
                {accumulationDiagnostics?.no_trade_reason && (
                  <Alert severity="warning">{t.noTradeReason}: {accumulationDiagnostics.no_trade_reason === 'score_never_reached_sell_threshold' ? t.reasonNeverReached : t.reasonAfterFinal}</Alert>
                )}
                <Divider />
                <Typography variant="subtitle2">{t.topScoreDates}</Typography>
                {topScoreDates.length > 0 ? (
                  <Stack spacing={0.5}>
                    {topScoreDates.map((row) => (
                      <Typography key={`${row.date}-${row.score}`} variant="body2" color="text.secondary">{row.date}: score {numSafe(row.score)} / close {numSafe(row.close)}</Typography>
                    ))}
                  </Stack>
                ) : (
                  <Typography variant="body2" color="text.secondary">{t.noScoreData}</Typography>
                )}
              </Stack>
            </CardContent>
          </Card>
        )}

        {chartData.length > 0 && (
          <Card>
            <CardHeader title={mode === 'accumulation' ? t.assetChart : t.priceChart} />
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ left: 8, right: 8 }}>
                  <XAxis dataKey="date" tickFormatter={(d) => dayjs(d).format('YY/MM/DD')} minTickGap={24} />
                  <YAxis tickFormatter={(v) => `${(v / 10000).toFixed(0)}万`} />
                  <Tooltip formatter={(val: number) => currencyFmt.format(val)} labelFormatter={(d) => dayjs(d as string).format('YYYY-MM-DD')} />
                  <Legend />
                  {mode === 'accumulation' ? (
                    <>
                      <Line type="monotone" dataKey="strategy" name={t.strategyLine} stroke="#7c3aed" dot={false} />
                      <Line type="monotone" dataKey="hold" name={t.holdLine} stroke="#10b981" dot={false} />
                    </>
                  ) : (
                    <>
                      <Line type="monotone" dataKey="close" name={t.closeLine} stroke="#7c3aed" dot={false} />
                      <Line type="monotone" dataKey="ma20" name="MA20" stroke="#0ea5e9" dot={false} />
                      <Line type="monotone" dataKey="ma60" name="MA60" stroke="#10b981" dot={false} />
                      <Line type="monotone" dataKey="ma200" name="MA200" stroke="#f97316" dot={false} />
                    </>
                  )}
                </LineChart>
              </ResponsiveContainer>
            </CardContent>
          </Card>
        )}
      </Stack>
    </Container>
  )
}

export default BacktestPage