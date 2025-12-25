import { LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer, Legend, CartesianGrid } from 'recharts'
import { Tooltip as MuiTooltip } from '@mui/material'
import { PricePoint } from '../types/api'
import type { TooltipTexts } from '../tooltipTexts'

type LegendLabels = {
  close?: string
  closeUsd?: string
  ma20?: string
  ma60?: string
  ma200?: string
}

type Props = {
  priceSeries: Array<PricePoint & { closeUsd?: number }>
  simple?: boolean
  tooltips: TooltipTexts
  legendLabels?: LegendLabels
}

function PriceChart({ priceSeries, simple = false, tooltips, legendLabels }: Props) {
  if (!priceSeries.length) {
    return (
      <ResponsiveContainer width="100%" height={240}>
        <LineChart data={[]}></LineChart>
      </ResponsiveContainer>
    )
  }

  const hasCloseUsd = priceSeries.some((p) => p.closeUsd !== undefined)

  return (
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={priceSeries} margin={{ top: 10, right: 20, bottom: 0, left: 0 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
        <XAxis
          dataKey="date"
          tick={{ fill: '#9ca3af', fontSize: 12 }}
          tickFormatter={(d) => (typeof d === 'string' ? d.slice(5) : d)}
          minTickGap={20}
        />
        <YAxis tick={{ fill: '#9ca3af' }} domain={['auto', 'auto']} />
        <RechartsTooltip contentStyle={{ background: '#0b1224', border: '1px solid #334155' }} labelFormatter={(l) => `日付: ${l}`} />
        {!simple && (
          <Legend
            formatter={(value) => {
              const map: Record<string, string> = {
                終値: legendLabels?.close ?? tooltips.chart.close,
                'ドル建て（終値）': legendLabels?.closeUsd ?? 'ドル建て（終値）',
                MA20: legendLabels?.ma20 ?? tooltips.chart.ma20,
                MA60: legendLabels?.ma60 ?? tooltips.chart.ma60,
                MA200: legendLabels?.ma200 ?? tooltips.chart.ma200,
              }
              return (
                <MuiTooltip title={map[value] ?? ''} arrow>
                  <span>{value}</span>
                </MuiTooltip>
              )
            }}
          />
        )}
        <Line type="monotone" dataKey="close" stroke="#7dd3fc" strokeWidth={2} dot={false} name={legendLabels?.close ?? '終値'} />
        {hasCloseUsd && (
          <Line
            type="monotone"
            dataKey="closeUsd"
            stroke="#22c55e"
            strokeWidth={2}
            dot={false}
            name={legendLabels?.closeUsd ?? 'ドル建て（終値）'}
          />
        )}
        <Line type="monotone" dataKey="ma20" stroke="#a78bfa" strokeWidth={2} dot={false} name="MA20" />
        <Line type="monotone" dataKey="ma60" stroke="#34d399" strokeWidth={2} dot={false} name="MA60" />
        <Line type="monotone" dataKey="ma200" stroke="#f59e0b" strokeWidth={2} dot={false} name="MA200" />
      </LineChart>
    </ResponsiveContainer>
  )
}

export default PriceChart
