import { useState } from 'react'
import { Card, CardContent, TextField, Button, Stack, Typography, Box, Divider, Tooltip } from '@mui/material'
import { EvaluateRequest, FundNavResponse, SyntheticNavResponse } from '../types/api'
import type { TooltipTexts } from '../tooltipTexts'

interface Props {
  onSubmit: (req: Pick<EvaluateRequest, 'total_quantity' | 'avg_cost'>) => void
  marketValue?: number
  pnl?: number
  syntheticNav?: SyntheticNavResponse | null
  fundNav?: FundNavResponse | null
  tooltips: TooltipTexts
}

function PositionForm({ onSubmit, marketValue, pnl, syntheticNav, fundNav, tooltips }: Props) {
  const [quantity, setQuantity] = useState('77384')
  const [avgCost, setAvgCost] = useState('21458')

  const jpyFormatter = new Intl.NumberFormat('ja-JP', {
    style: 'currency',
    currency: 'JPY',
    maximumFractionDigits: 0,
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    onSubmit({ total_quantity: parseFloat(quantity), avg_cost: parseFloat(avgCost) })
  }

  return (
    <Card>
      <CardContent>
        <Stack component="form" spacing={2} onSubmit={handleSubmit}>
          <Tooltip title={tooltips.position.card} arrow>
            <Typography variant="h6" component="div">ポジション入力</Typography>
          </Tooltip>
          <NavInfo syntheticNav={syntheticNav} fundNav={fundNav} tooltips={tooltips} />
          <Tooltip title={tooltips.position.quantity} arrow>
            <TextField
              label="保有数量"
            type="number"
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            InputProps={{ inputProps: { min: 0, step: 0.1 } }}
            />
          </Tooltip>
          <Tooltip title={tooltips.position.avgCost} arrow>
            <TextField
              label="平均取得単価（円）"
            type="number"
            value={avgCost}
            onChange={(e) => setAvgCost(e.target.value)}
            InputProps={{ inputProps: { min: 0, step: 10 } }}
            />
          </Tooltip>
          <Tooltip title={tooltips.position.submit} arrow>
            <Button type="submit" variant="contained" size="large">
              計算
            </Button>
          </Tooltip>
          <Divider />
          <Box display="flex" gap={2}>
            <Metric label="評価額" tooltip={tooltips.position.marketValue} value={marketValue} formatter={jpyFormatter} />
            <Metric
              label="含み損益"
              tooltip={tooltips.position.pnl}
              value={pnl}
              formatter={jpyFormatter}
              color={pnl && pnl >= 0 ? 'primary' : 'error'}
            />
          </Box>
        </Stack>
      </CardContent>
    </Card>
  )
}

function Metric({
  label,
  tooltip,
  value,
  formatter,
  color,
}: {
  label: string
  tooltip: string
  value?: number
  formatter?: Intl.NumberFormat
  color?: 'primary' | 'error'
}) {
  const display = value !== undefined ? formatter?.format(value) ?? value.toFixed(2) : '--'
  return (
    <Box>
      <Tooltip title={tooltip} arrow>
        <Typography variant="caption" color="text.secondary" component="div">
          {label}
        </Typography>
      </Tooltip>
      <Typography variant="h6" color={color ?? 'text.primary'}>
        {display}
      </Typography>
    </Box>
  )
}

function NavInfo({
  syntheticNav,
  fundNav,
  tooltips,
}: {
  syntheticNav?: SyntheticNavResponse | null
  fundNav?: FundNavResponse | null
  tooltips: TooltipTexts
}) {
  const formatter = new Intl.NumberFormat('ja-JP', { style: 'currency', currency: 'JPY', maximumFractionDigits: 0 })
  const synthetic = syntheticNav ? formatter.format(syntheticNav.navJpy) : '--'
  const official = fundNav ? formatter.format(fundNav.navJpy) : null
  return (
    <Stack spacing={0.5}>
      {official && (
        <Tooltip title={tooltips.position.navOfficial} arrow>
          <Typography variant="body2" color="text.secondary">
            公式基準価額（取得日: {fundNav?.asOf}）: <strong>{official}</strong>
          </Typography>
        </Tooltip>
      )}
      <Tooltip title={tooltips.position.navSynthetic} arrow>
        <Typography variant="body2" color="text.secondary">
          参考基準価額（{syntheticNav?.asOf ?? 'n/a'}）: <strong>{synthetic}</strong>
        </Typography>
      </Tooltip>
    </Stack>
  )
}

export default PositionForm
