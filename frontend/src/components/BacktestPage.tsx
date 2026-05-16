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
  Divider,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
} from '@mui/material'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import dayjs from 'dayjs'
import { runBacktest } from '../apis'
import type { BacktestRequest, BacktestResult } from '../types/apis'
import { INDEX_LABELS, type IndexType } from '../types/index'
import { getBacktestViewStatus, toBacktestIndexType } from '../utils/indexTypeMap'

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
const DEFAULT_LONG_PRECOMPUTED_START_DATES = ['2010-01-01', '2015-01-01']
const PRECOMPUTED_END_DATE = '2025-12-31'
const RUNTIME_MAX_DAYS = 366 * 5
const PRECOMPUTED_INITIAL_CASH = 1_000_000
const PRECOMPUTED_SELL_THRESHOLD = 80
const PRECOMPUTED_BUY_THRESHOLD = 40
const PRECOMPUTED_SCORE_MA = 200

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
    getPrecomputedStartDates(request.index_type).includes(request.start_date) &&
    request.end_date === PRECOMPUTED_END_DATE &&
    Number(request.initial_cash) === PRECOMPUTED_INITIAL_CASH &&
    Number(request.sell_threshold) === PRECOMPUTED_SELL_THRESHOLD &&
    Number(request.buy_threshold) === PRECOMPUTED_BUY_THRESHOLD &&
    Number(request.score_ma) === PRECOMPUTED_SCORE_MA
  )
}

const getBacktestValidationError = (request: BacktestRequest): string | null => {
  if (isPrecomputedRequest(request)) return null
  if (isRuntimeRangeAllowed(request.start_date, request.end_date)) return null

  const availableStarts = getPrecomputedStartDates(request.index_type).join(' / ')
  return (
    `5年超のバックテストは事前計算済み期間のみ利用できます。` +
    `対象インデックスの開始日は ${availableStarts}、終了日は ${PRECOMPUTED_END_DATE}、` +
    `初期資金100万円・売り80・買い40・MA200にしてください。`
  )
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

export function BacktestPage() {
  const [params, setParams] = useState<BacktestRequest>(DEFAULT_REQUEST)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleChange = (key: keyof BacktestRequest, value: string | number) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const handleIndexChange = (indexType: IndexType) => {
    setParams((prev) => ({
      ...prev,
      index_type: indexType,
      start_date: BACKTEST_START_DATES[indexType],
      end_date: PRECOMPUTED_END_DATE,
      initial_cash: PRECOMPUTED_INITIAL_CASH,
      sell_threshold: PRECOMPUTED_SELL_THRESHOLD,
      buy_threshold: PRECOMPUTED_BUY_THRESHOLD,
      score_ma: PRECOMPUTED_SCORE_MA,
    }))
    setResult(null)
    setError(null)
  }

  const handleRun = async () => {
    const validationError = getBacktestValidationError(params)
    if (validationError) {
      setError(validationError)
      setResult(null)
      return
    }

    try {
      setLoading(true)
      setError(null)
      const res = await runBacktest({ ...params, index_type: toBacktestIndexType(params.index_type) })
      setResult(res)
    } catch (e: any) {
      setError(e.message ?? 'バックテストに失敗しました')
    } finally {
      setLoading(false)
    }
  }


  const noClearSellStatus = getBacktestViewStatus(params.index_type, result?.summary.trade_count)
  const chartData = (result?.equity_curve || []).map((point) => ({
    date: point.date,
    close: point.close,
    ma20: point.ma20 ?? null,
    ma60: point.ma60 ?? null,
    ma200: point.ma200 ?? null,
  }))
  const startDateHelperText = `5年超は ${getPrecomputedStartDates(params.index_type).join(' / ')} のみ対応`

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      <Stack spacing={3}>
        <Typography variant="h4" fontWeight={700} color="primary.light">
          バックテスト専用ページ
        </Typography>
        <Card>
          <CardHeader title="パラメータ" />
          <CardContent>
            {error && (
              <Alert severity="error" sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}
            <Grid container spacing={2}>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  label="開始日"
                  type="date"
                  fullWidth
                  value={params.start_date}
                  onChange={(e) => handleChange('start_date', e.target.value)}
                  InputLabelProps={{ shrink: true }}
                  helperText={startDateHelperText}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  label="終了日"
                  type="date"
                  fullWidth
                  value={params.end_date}
                  onChange={(e) => handleChange('end_date', e.target.value)}
                  InputLabelProps={{ shrink: true }}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  label="初期資金"
                  type="number"
                  fullWidth
                  value={params.initial_cash}
                  onChange={(e) => handleChange('initial_cash', Number(e.target.value))}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="index-select">対象インデックス</InputLabel>
                  <Select
                    labelId="index-select"
                    value={params.index_type}
                    label="対象インデックス"
                    onChange={(e) => handleIndexChange(e.target.value as IndexType)}
                  >
                    {(Object.keys(INDEX_LABELS) as IndexType[]).map((key) => (
                      <MenuItem key={key} value={key}>
                        {INDEX_LABELS[key]}
                      </MenuItem>
                    ))}
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  label="売りしきい値"
                  type="number"
                  fullWidth
                  value={params.sell_threshold}
                  onChange={(e) => handleChange('sell_threshold', Number(e.target.value))}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <TextField
                  label="買い戻ししきい値"
                  type="number"
                  fullWidth
                  value={params.buy_threshold}
                  onChange={(e) => handleChange('buy_threshold', Number(e.target.value))}
                />
              </Grid>
              <Grid item xs={12} sm={6} md={3}>
                <FormControl fullWidth size="small">
                  <InputLabel id="score-ma-select">スコア算出MA</InputLabel>
                  <Select
                    labelId="score-ma-select"
                    value={params.score_ma}
                    label="スコア算出MA"
                    onChange={(e) => handleChange('score_ma', Number(e.target.value))}
                  >
                    <MenuItem value={20}>20日（短期・2〜6週間）</MenuItem>
                    <MenuItem value={60}>60日（中期・1〜3か月）</MenuItem>
                    <MenuItem value={200}>200日（長期・3か月〜1年）</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12}>
                <Button variant="contained" onClick={handleRun} disabled={loading}>
                  {loading ? '計算中...' : 'バックテスト実行'}
                </Button>
              </Grid>
            </Grid>
          </CardContent>
        </Card>

        <Card>
          <CardHeader title="成績" subheader={result ? `${params.start_date}〜${params.end_date}` : undefined} />
          <CardContent>
            {result ? (
              <Stack spacing={0.5}>
                <Typography variant="body2">
                  最終資産: <strong>{currencySafe(result.summary.final_equity)}</strong>
                </Typography>
                <Typography variant="body2">
                  単純ホールド: <strong>{currencySafe(result.summary.hold_equity)}</strong>
                </Typography>
                <Typography variant="body2">
                  トータルリターン: <strong>{pctFmt(result.summary.total_return)}</strong>
                </Typography>
                <Typography variant="body2">
                  最大ドローダウン: <strong>{pctFmt(result.summary.max_drawdown)}</strong>
                </Typography>
                <Typography variant="body2">
                  売買回数: <strong>{result.summary.trade_count ?? '-'} 回</strong>
                </Typography>
                {getBacktestViewStatus(result.summary.trade_count) && (
                  <Typography variant="body2" color="text.secondary">
                    {getBacktestViewStatus(result.summary.trade_count)}
                  </Typography>
                )}
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                パラメータを設定して「バックテスト実行」を押してください。
              </Typography>
            )}
          </CardContent>
        </Card>

        {result?.equity_curve && result.equity_curve.length > 0 && (
          <Card>
            <CardHeader title="価格推移" />
            <CardContent>
              <ResponsiveContainer width="100%" height={320}>
                <LineChart data={chartData} margin={{ left: 8, right: 8 }}>
                  <XAxis
                    dataKey="date"
                    tickFormatter={(d) => dayjs(d).format('YY/MM/DD')}
                    minTickGap={24}
                  />
                  <YAxis tickFormatter={(v) => `${(v / 10000).toFixed(0)}万`} />
                  <Tooltip
                    formatter={(val: number) => currencyFmt.format(val)}
                    labelFormatter={(d) => dayjs(d as string).format('YYYY-MM-DD')}
                  />
                  <Legend />
                  <Line type="monotone" dataKey="close" name="終値" stroke="#7c3aed" dot={false} />
                  <Line type="monotone" dataKey="ma20" name="MA20" stroke="#0ea5e9" dot={false} />
                  <Line type="monotone" dataKey="ma60" name="MA60" stroke="#10b981" dot={false} />
                  <Line type="monotone" dataKey="ma200" name="MA200" stroke="#f97316" dot={false} />
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
