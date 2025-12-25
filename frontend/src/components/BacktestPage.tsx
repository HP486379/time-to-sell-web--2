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
} from '@mui/material'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, Legend } from 'recharts'
import dayjs from 'dayjs'
import { runBacktest } from '../apis'
import type { BacktestRequest, BacktestResult } from '../types/apis'
import { INDEX_LABELS, type IndexType } from '../types/index'

const DEFAULT_REQUEST: BacktestRequest = {
  start_date: '2014-01-01',
  end_date: '2024-11-30',
  initial_cash: 1_000_000,
  sell_threshold: 80,
  buy_threshold: 40,
  index_type: 'SP500',
  score_ma: 200,
}

const currencyFmt = new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 })
const pctFmt = (v: unknown) => {
  const num = typeof v === 'number' ? v : typeof v === 'string' ? Number(v) : NaN
  return Number.isFinite(num) ? `${num.toFixed(2)} %` : '-'
}

export function BacktestPage() {
  const [params, setParams] = useState<BacktestRequest>(DEFAULT_REQUEST)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleChange = (key: keyof BacktestRequest, value: string | number) => {
    setParams((prev) => ({ ...prev, [key]: value }))
  }

  const handleRun = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await runBacktest(params)
      setResult(res)
    } catch (e: any) {
      setError(e.message ?? 'バックテストに失敗しました')
    } finally {
      setLoading(false)
    }
  }

  const chartData = (result?.portfolio_history || []).map((p, idx) => ({
    ...p,
    buyHold: result?.buy_hold_history?.[idx]?.value ?? null,
  }))

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
                    onChange={(e) => handleChange('index_type', e.target.value as IndexType)}
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
                  最終資産: <strong>{currencyFmt.format(result.final_value)}</strong>
                </Typography>
                <Typography variant="body2">
                  単純ホールド: <strong>{currencyFmt.format(result.buy_and_hold_final)}</strong>
                </Typography>
                <Typography variant="body2">
                  トータルリターン: <strong>{pctFmt(result.total_return_pct)}</strong>
                </Typography>
                <Typography variant="body2">
                  最大ドローダウン: <strong>{pctFmt(result.max_drawdown_pct)}</strong>
                </Typography>
                <Typography variant="body2">
                  売買回数: <strong>{result.trade_count ?? '-'} 回</strong>
                </Typography>
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                パラメータを設定して「バックテスト実行」を押してください。
              </Typography>
            )}
          </CardContent>
        </Card>

        {result?.portfolio_history && result.portfolio_history.length > 0 && (
          <Card>
            <CardHeader title="資産推移" />
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
                  <Line type="monotone" dataKey="value" name="戦略" stroke="#7c3aed" dot={false} />
                  <Line type="monotone" dataKey="buyHold" name="ホールド" stroke="#10b981" dot={false} />
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
