import { Empty, Spin, Tag } from 'antd'
import type { AnnualCalendar, AnnualMonth, ScalarValue } from '../../types/api'
import { shortId } from '../../utils/format'

type MetricKey =
  | 'calendarWorkingDays'
  | 'productionDays'
  | 'doubleShiftDays'
  | 'capacityHeadroom'
  | 'pr'
  | 'ws'
  | 'ppTarget'
  | 'ppRealized'
  | 'inventory'
  | 'prBalance'
  | 'issueCount'

type Snapshot = Record<MetricKey, number | null>

type MatrixRow = {
  label: string
  side: 'left' | 'right' | 'delta' | 'cumulative'
  values: Array<number | null>
  total: number | null
}

type MatrixGroup = {
  title: string
  tone: 'capacity' | 'demand' | 'production' | 'inventory'
  rows: MatrixRow[]
}

const MONTH_LABELS = ['1月', '2月', '3月', '4月', '5月', '6月', '7月', '8月', '9月', '10月', '11月', '12月']

function numberValue(value: ScalarValue): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function monthSnapshot(month: AnnualMonth | undefined): Snapshot {
  if (!month) {
    return {
      calendarWorkingDays: null,
      productionDays: null,
      doubleShiftDays: null,
      capacityHeadroom: null,
      pr: null,
      ws: null,
      ppTarget: null,
      ppRealized: null,
      inventory: null,
      prBalance: null,
      issueCount: null,
    }
  }
  return {
    calendarWorkingDays: month.days.filter((day) => day.calendar_state === 'WORKING').length,
    productionDays: month.days.filter((day) => Number(day.planned_units || 0) > 0).length,
    doubleShiftDays: month.days.filter((day) => Number(day.planned_units || 0) > 0 && day.working_mode_summary?.includes('DOUBLE_SHIFT')).length,
    capacityHeadroom: numberValue(month.capacity_headroom),
    pr: numberValue(month.pr_total),
    ws: numberValue(month.ws_total),
    ppTarget: numberValue(month.pp_target),
    ppRealized: numberValue(month.pp_realized),
    inventory: numberValue(month.inventory_eom),
    prBalance: numberValue(month.pr_balance),
    issueCount: Number(month.issue_count ?? 0),
  }
}

function valuesFor(snapshots: Snapshot[], key: MetricKey): Array<number | null> {
  return snapshots.map((snapshot) => snapshot[key])
}

function deltaValues(left: Array<number | null>, right: Array<number | null>): Array<number | null> {
  return left.map((value, index) => (
    value === null || right[index] === null ? null : (right[index] as number) - value
  ))
}

function cumulative(values: Array<number | null>): Array<number | null> {
  let running = 0
  let hasValue = false
  return values.map((value) => {
    if (value !== null) {
      running += value
      hasValue = true
    }
    return hasValue ? running : null
  })
}

function total(values: Array<number | null>, mode: 'sum' | 'last'): number | null {
  const present = values.filter((value): value is number => value !== null)
  if (present.length === 0) return null
  return mode === 'last' ? present[present.length - 1] : present.reduce((sum, value) => sum + value, 0)
}

function metricRows(
  label: string,
  key: MetricKey,
  left: Snapshot[],
  right: Snapshot[],
  options: { cumulativeDelta?: boolean; totalMode?: 'sum' | 'last' } = {},
): MatrixRow[] {
  const leftValues = valuesFor(left, key)
  const rightValues = valuesFor(right, key)
  const deltas = deltaValues(leftValues, rightValues)
  const totalMode = options.totalMode || 'sum'
  const rows: MatrixRow[] = [
    { label: `${label} · 左版本`, side: 'left', values: leftValues, total: total(leftValues, totalMode) },
    { label: `${label} · 右版本`, side: 'right', values: rightValues, total: total(rightValues, totalMode) },
    { label: `${label} · 差额`, side: 'delta', values: deltas, total: total(deltas, totalMode) },
  ]
  if (options.cumulativeDelta) {
    const accumulated = cumulative(deltas)
    rows.push({ label: `${label} · 累计差额`, side: 'cumulative', values: accumulated, total: total(accumulated, 'last') })
  }
  return rows
}

function displayNumber(value: number | null): string {
  if (value === null) return '—'
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(value)
}

function valueClass(value: number | null, side: MatrixRow['side']): string {
  if (value === null) return 'is-empty'
  if ((side === 'delta' || side === 'cumulative') && value < 0) return 'is-negative'
  if ((side === 'delta' || side === 'cumulative') && value > 0) return 'is-positive'
  return ''
}

export function ProductionOverviewMatrix({
  leftId,
  rightId,
  leftAnnual,
  rightAnnual,
  loading,
}: {
  leftId: string
  rightId: string
  leftAnnual?: AnnualCalendar
  rightAnnual?: AnnualCalendar
  loading: boolean
}) {
  if (loading) {
    return <div className="production-matrix-state"><Spin size="small" /> 正在加载月度生产投影…</div>
  }
  if (!leftAnnual || !rightAnnual) {
    return <div className="production-matrix-state"><Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="月度投影未提供，已保留后端对比结论" /></div>
  }

  const year = leftAnnual.months[0]?.month.slice(0, 4) || rightAnnual.months[0]?.month.slice(0, 4) || '年度'
  const monthKeys = Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, '0')}`)
  const leftByMonth = new Map(leftAnnual.months.map((month) => [month.month, month]))
  const rightByMonth = new Map(rightAnnual.months.map((month) => [month.month, month]))
  const leftSnapshots = monthKeys.map((month) => monthSnapshot(leftByMonth.get(month)))
  const rightSnapshots = monthKeys.map((month) => monthSnapshot(rightByMonth.get(month)))

  const groups: MatrixGroup[] = [
    {
      title: '日历与产能',
      tone: 'capacity',
      rows: [
        ...metricRows('日历工作日', 'calendarWorkingDays', leftSnapshots, rightSnapshots),
        ...metricRows('实际生产天数', 'productionDays', leftSnapshots, rightSnapshots),
        ...metricRows('双班生产天数', 'doubleShiftDays', leftSnapshots, rightSnapshots),
        ...metricRows('产能余量', 'capacityHeadroom', leftSnapshots, rightSnapshots),
      ],
    },
    {
      title: '需求与批发',
      tone: 'demand',
      rows: [
        ...metricRows('PR', 'pr', leftSnapshots, rightSnapshots, { cumulativeDelta: true }),
        ...metricRows('WS', 'ws', leftSnapshots, rightSnapshots, { cumulativeDelta: true }),
      ],
    },
    {
      title: '生产计划',
      tone: 'production',
      rows: [
        ...metricRows('PP 目标', 'ppTarget', leftSnapshots, rightSnapshots, { cumulativeDelta: true }),
        ...metricRows('PP 实绩', 'ppRealized', leftSnapshots, rightSnapshots, { cumulativeDelta: true }),
      ],
    },
    {
      title: '库存与风险',
      tone: 'inventory',
      rows: [
        ...metricRows('期末成品库存', 'inventory', leftSnapshots, rightSnapshots, { totalMode: 'last' }),
        ...metricRows('PR 结余', 'prBalance', leftSnapshots, rightSnapshots, { totalMode: 'last' }),
        ...metricRows('待处理问题', 'issueCount', leftSnapshots, rightSnapshots),
      ],
    },
  ]

  return (
    <div className="production-overview" data-testid="production-overview-matrix">
      <div className="production-overview-head">
        <div>
          <span className="production-overview-kicker">PRODUCTION OVERVIEW</span>
          <h2>{year} 年生产计划版本对比</h2>
          <p>月份横向对齐，左/右版本与差额纵向分组。</p>
        </div>
        <div className="production-overview-legend">
          <Tag className="matrix-version-tag left">左 {shortId(leftId)}</Tag>
          <Tag className="matrix-version-tag right">右 {shortId(rightId)}</Tag>
          <span><i className="matrix-swatch delta" />差额=右-左</span>
        </div>
      </div>
      <div className="production-matrix-scroll">
        <table className="production-matrix">
          <thead>
            <tr>
              <th className="matrix-label-column">指标 / 版本</th>
              {MONTH_LABELS.map((month) => <th key={month}>{month}</th>)}
              <th className="matrix-total-column">年度汇总</th>
            </tr>
          </thead>
          <tbody>
            {groups.map((group) => (
              <MatrixGroupRows key={group.title} group={group} />
            ))}
          </tbody>
        </table>
      </div>
      <div className="production-overview-note">数据来自两个 PlanVersion 的后端年度投影；差额仅用于展示，确认门禁仍以后端结果为准。</div>
    </div>
  )
}

function MatrixGroupRows({ group }: { group: MatrixGroup }) {
  return (
    <>
      <tr className={`matrix-group-row tone-${group.tone}`}>
        <th colSpan={14}>{group.title}</th>
      </tr>
      {group.rows.map((row) => (
        <tr key={row.label} className={`matrix-data-row side-${row.side} tone-${group.tone}`}>
          <th className="matrix-label-column">{row.label}</th>
          {row.values.map((value, index) => (
            <td key={`${row.label}-${index}`} className={valueClass(value, row.side)}>{displayNumber(value)}</td>
          ))}
          <td className={`matrix-total-column ${valueClass(row.total, row.side)}`}>{displayNumber(row.total)}</td>
        </tr>
      ))}
    </>
  )
}
