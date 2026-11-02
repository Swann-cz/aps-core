import type { ReactNode } from 'react'
import type { AnnualMonth } from '../api/core'

const chartWidth = 520
const chartHeight = 210
const padding = { top: 20, right: 20, bottom: 32, left: 46 }

function numeric(value: string | number | boolean | null): number | null {
  if (value === null || typeof value === 'boolean') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function label(value: string | number | boolean | null) {
  return numeric(value)?.toLocaleString('zh-CN') ?? '—'
}

export function LineMetricChart({ months, series }: { months: AnnualMonth[]; series: { key: keyof AnnualMonth; label: string; color: string }[] }) {
  const values = series.flatMap((item) => months.map((month) => numeric(month[item.key] as string | number | boolean | null))).filter((value): value is number => value !== null)
  const min = values.length ? Math.min(0, ...values) : 0
  const max = values.length ? Math.max(...values, 1) : 1
  const plotWidth = chartWidth - padding.left - padding.right
  const plotHeight = chartHeight - padding.top - padding.bottom
  const x = (index: number) => padding.left + (months.length <= 1 ? plotWidth / 2 : index * plotWidth / (months.length - 1))
  const y = (value: number) => padding.top + plotHeight - ((value - min) / (max - min || 1)) * plotHeight
  const ticks = [0, 0.5, 1].map((ratio) => min + (max - min) * ratio)

  return <div className="metric-chart">
    <div className="chart-legend">{series.map((item) => <span key={item.label}><i style={{ background: item.color }} />{item.label}</span>)}</div>
    <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label="年度趋势图">
      {ticks.map((tick) => <g key={tick}>
        <line x1={padding.left} x2={chartWidth - padding.right} y1={y(tick)} y2={y(tick)} className="chart-grid" />
        <text x={padding.left - 8} y={y(tick) + 4} textAnchor="end" className="chart-axis">{Math.round(tick).toLocaleString('zh-CN')}</text>
      </g>)}
      {months.map((month, index) => <text key={month.month} x={x(index)} y={chartHeight - 8} textAnchor="middle" className="chart-axis">{month.month.slice(5)}月</text>)}
      {series.map((item) => {
        const points = months.map((month, index) => {
          const value = numeric(month[item.key] as string | number | boolean | null)
          return value === null ? null : `${x(index)},${y(value)}`
        }).filter((point): point is string => point !== null).join(' ')
        return <g key={item.label}>
          <polyline points={points} fill="none" stroke={item.color} strokeWidth="2.5" />
          {months.map((month, index) => {
            const value = numeric(month[item.key] as string | number | boolean | null)
            return value === null ? null : <circle key={`${item.label}-${month.month}`} cx={x(index)} cy={y(value)} r="3.5" fill={item.color} />
          })}
        </g>
      })}
    </svg>
  </div>
}

export function BarMetricChart({ months, field, color, title }: { months: AnnualMonth[]; field: keyof AnnualMonth; color: string; title: ReactNode }) {
  const values = months.map((month) => numeric(month[field] as string | number | boolean | null))
  const max = Math.max(...values.filter((value): value is number => value !== null), 1)
  return <div className="metric-chart bar-chart" aria-label={String(title)}>
    <div className="bar-plot">
      {months.map((month, index) => {
        const value = values[index]
        return <div className="bar-column" key={month.month}>
          <span className="bar-value">{label(value)}</span>
          <div className="bar-track"><div className="bar-fill" style={{ height: `${value === null ? 0 : Math.max(3, value / max * 100)}%`, background: color }} /></div>
          <span className="chart-axis">{month.month.slice(5)}月</span>
        </div>
      })}
    </div>
  </div>
}
