import { Button, Empty, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { StatusTag } from '../../components/StatusTag'
import type { DailySpecialEffect, EffectEvidenceStatus, MonthlyDay, MonthlyNodeFlow, PlanningDayEffect, PlanningEffectNodeId, ScalarValue } from '../../types/api'
import { displayValue, formatDate } from '../../utils/format'
import { FillingMatrix } from './FillingMatrix'

export type FillingRow = {
  key: string
  group: string
  measure: string
  field?: keyof MonthlyDay | null
  editRef?: keyof MonthlyDay | null
  sectionEnd?: boolean
  total?: boolean
  conditionMarker?: boolean
  nodeId?: PlanningEffectNodeId
  nodeFlowRole?: MonthlyNodeFlow['role']
  nodeFlowField?: 'bod' | 'in' | 'out' | 'eod'
  typeclassId?: string
}

export type FillingConditionBadge = {
  key: string
  label: string
  color: string
  group: string
}

export type CandidateMonthlyDay = MonthlyDay & {
  shutdown_day?: boolean
  special_effects?: DailySpecialEffect[]
}

export const FILLING_ROWS: FillingRow[] = [
  { key: 'production-mode', group: '生产参数', measure: 'WorkingMode', field: 'working_mode' },
  { key: 'production-hours', group: '生产参数', measure: 'Hours', field: 'hours' },
  { key: 'production-jph', group: '生产参数', measure: 'JPH', field: 'jph' },
  { key: 'condition-marker', group: '生产参数', measure: 'Condition Marker', conditionMarker: true, sectionEnd: true },
  { key: 'bs1-in', group: 'Body Shop', measure: 'BS1 · in', field: 'bs1_in', total: true, nodeId: 'BS1' },
  { key: 'bs1-in-cum', group: 'Body Shop', measure: 'BS1 · in cumulative', field: 'bs1_in_cumulative', nodeId: 'BS1' },
  { key: 'bs1-out', group: 'Body Shop', measure: 'BS1 · out', field: 'bs1_out', editRef: 'bs1_out', total: true, nodeId: 'BS1' },
  { key: 'bs1-out-cum', group: 'Body Shop', measure: 'BS1 · out cumulative', field: 'bs1_out_cumulative', nodeId: 'BS1' },
  { key: 'bs2-in', group: 'Body Shop', measure: 'BS2 · in', field: 'bs2_in', total: true, nodeId: 'BS2' },
  { key: 'bs2-in-cum', group: 'Body Shop', measure: 'BS2 · in cumulative', field: 'bs2_in_cumulative', nodeId: 'BS2' },
  { key: 'bs2-out', group: 'Body Shop', measure: 'BS2 · out', field: 'bs2_out', editRef: 'bs2_out', total: true, nodeId: 'BS2' },
  { key: 'bs2-out-cum', group: 'Body Shop', measure: 'BS2 · out cumulative', field: 'bs2_out_cumulative', sectionEnd: true, nodeId: 'BS2' },
  { key: 'ps-in', group: 'Paint Shop', measure: 'in', field: 'ps_in', total: true, nodeId: 'PS' },
  { key: 'ps-in-cum', group: 'Paint Shop', measure: 'in cumulative', field: 'ps_in_cumulative', nodeId: 'PS' },
  { key: 'ps-out', group: 'Paint Shop', measure: 'out', field: 'ps_out', editRef: 'ps_out', total: true, nodeId: 'PS' },
  { key: 'ps-out-cum', group: 'Paint Shop', measure: 'out cumulative', field: 'ps_out_cumulative', sectionEnd: true, nodeId: 'PS' },
  { key: 'as-in', group: 'Assembly Shop', measure: 'in', field: 'as_in', total: true, nodeId: 'AS' },
  { key: 'as-in-cum', group: 'Assembly Shop', measure: 'in cumulative', field: 'as_in_cumulative', nodeId: 'AS' },
  { key: 'as-out', group: 'Assembly Shop', measure: 'out', field: 'as_out', editRef: 'as_out', total: true, nodeId: 'AS' },
  { key: 'as-out-cum', group: 'Assembly Shop', measure: 'out cumulative', field: 'as_out_cumulative', sectionEnd: true, nodeId: 'AS' },
  { key: 'finish-in', group: '累计值与库存', measure: 'in', field: 'as_out', total: true, nodeId: 'FINISHED' },
  { key: 'finish-in-cum', group: '累计值与库存', measure: 'in cumulative', field: 'as_out_cumulative', nodeId: 'FINISHED' },
  { key: 'finish-out', group: '累计值与库存', measure: 'out', field: 'finished_output', total: true, nodeId: 'FINISHED' },
  { key: 'finish-out-cum', group: '累计值与库存', measure: 'out cumulative', field: 'finished_output_cumulative', sectionEnd: true, nodeId: 'FINISHED' },
  { key: 'wip-bs1', group: 'WIP 与缓冲', measure: 'BS1', field: 'bs1_eod', nodeId: 'BS1' },
  { key: 'wip-bs2', group: 'WIP 与缓冲', measure: 'BS2', field: 'bs2_eod', nodeId: 'BS2' },
  { key: 'wip-wbs', group: 'WIP 与缓冲', measure: 'WBS', field: 'wbs_eod', nodeId: 'WBS' },
  { key: 'wip-ps', group: 'WIP 与缓冲', measure: 'PS', field: 'ps_eod', nodeId: 'PS' },
  { key: 'wip-pbs', group: 'WIP 与缓冲', measure: 'PBS', field: 'pbs_eod', nodeId: 'PBS' },
  { key: 'wip-as', group: 'WIP 与缓冲', measure: 'AS', field: 'as_eod', nodeId: 'AS' },
  { key: 'wip-finish', group: 'WIP 与缓冲', measure: '成品', field: 'finished_inventory_eod', sectionEnd: true, nodeId: 'FINISHED' },
]

const V6_NODE_GROUPS: Array<{
  role: MonthlyNodeFlow['role']
  group: string
  nodeId: PlanningEffectNodeId
}> = [
  { role: 'WBS', group: 'WBS 缓冲区', nodeId: 'WBS' },
  { role: 'PS', group: 'Paint Shop', nodeId: 'PS' },
  { role: 'PBS', group: 'PBS 缓冲区', nodeId: 'PBS' },
  { role: 'MAINLINE', group: 'AS Mainline', nodeId: 'AS_MAINLINE' },
  { role: 'FINISH', group: 'AS Finish Line', nodeId: 'AS_FINISH_LINE' },
]

const V6_NODE_FIELDS: Array<{ field: 'bod' | 'in' | 'out' | 'eod'; label: string }> = [
  { field: 'bod', label: 'BOD' },
  { field: 'in', label: 'IN' },
  { field: 'out', label: 'OUT' },
  { field: 'eod', label: 'EOD' },
]

function v6TypeclassIds(days: CandidateMonthlyDay[]): string[] {
  return Array.from(new Set(
    days.flatMap((day) => (
      day.node_flows?.flatMap((flow) => (
        flow.typeclass_flows?.map((item) => item.typeclass_id) || []
      )) || []
    )),
  )).sort()
}

function v6NodeRows(days: CandidateMonthlyDay[]): FillingRow[] {
  const typeclassIds = v6TypeclassIds(days)
  const nodeRows = V6_NODE_GROUPS.flatMap(({ role, group, nodeId }) => {
    const rowsFor = (scope: 'total' | string, typeclassId?: string) => (
      V6_NODE_FIELDS.map(({ field, label }) => {
        const outputLabel = role === 'FINISH' && field === 'out' ? 'FOK（OUT）' : label
        return {
          key: `${role.toLowerCase()}-${scope}-${field}`,
          group,
          measure: `${scope === 'total' ? '合计' : scope} · ${outputLabel}`,
          total: field === 'in' || field === 'out',
          sectionEnd: field === 'eod',
          nodeId,
          nodeFlowRole: role,
          nodeFlowField: field,
          typeclassId,
        } satisfies FillingRow
      })
    )
    return [
      ...rowsFor('total'),
      ...typeclassIds.flatMap((typeclassId) => rowsFor(typeclassId, typeclassId)),
    ]
  })
  return [
    ...FILLING_ROWS.filter((row) => (
      row.group !== 'Paint Shop'
      && row.group !== 'Assembly Shop'
      && row.group !== '累计值与库存'
      && row.group !== 'WIP 与缓冲'
    )),
    ...nodeRows,
    ...FILLING_ROWS.filter((row) => (
      row.group === 'WIP 与缓冲'
      && !['wip-wbs', 'wip-ps', 'wip-pbs', 'wip-as'].includes(row.key)
    )),
  ]
}

const FILLING_GROUPS = ['生产参数', 'Body Shop', 'Paint Shop', 'Assembly Shop', '累计值与库存', 'WIP 与缓冲'] as const
const V6_FILLING_GROUPS = ['生产参数', 'Body Shop', 'WBS 缓冲区', 'Paint Shop', 'PBS 缓冲区', 'AS Mainline', 'AS Finish Line', 'WIP 与缓冲'] as const

export function readFillingRowValue(day: CandidateMonthlyDay, row: FillingRow): ScalarValue {
  if (row.nodeFlowRole && row.nodeFlowField) {
    const flow = day.node_flows?.find((item) => item.role === row.nodeFlowRole)
    if (row.typeclassId) {
      return flow?.typeclass_flows?.find(
        (item) => item.typeclass_id === row.typeclassId,
      )?.[row.nodeFlowField] ?? null
    }
    return flow?.[row.nodeFlowField] ?? null
  }
  return row.field ? day[row.field] as ScalarValue : null
}

function rowMonthlyTotal(row: FillingRow, days: CandidateMonthlyDay[]): number | null {
  if (!row.total) return null
  let found = false
  const total = days.reduce((sum, day) => {
    const value = readFillingRowValue(day, row)
    const number = typeof value === 'number' ? value : typeof value === 'string' && value.trim() !== '' ? Number(value) : NaN
    if (!Number.isFinite(number)) return sum
    found = true
    return sum + number
  }, 0)
  return row.nodeFlowRole && !found ? null : total
}

const effectMeta: Record<string, { label: string; className: string; priority: number }> = {
  WINDOW_MERGED: { label: '并窗', className: 'day-boundary-badge', priority: 7 },
  WORKDAY_RELOCATED_OUT: { label: '工作日移出', className: 'day-shutdown-badge', priority: 7 },
  WORKDAY_RELOCATED_IN: { label: '工作日移入', className: 'day-restart-badge', priority: 7 },
  SHUTDOWN: { label: '停线', className: 'day-shutdown-badge', priority: 6 },
  CLEARING: { label: '清线', className: 'day-clear-badge', priority: 5 },
  LINE_REFILL: { label: '复线', className: 'day-restart-badge', priority: 4 },
  BOUNDARY_NOTICE: { label: '边界提示', className: 'day-boundary-badge', priority: 1 },
}

export function FillingBusinessView({
  days,
  conditionByDate = {},
  effectEvidenceStatus,
  renderCell,
  emptyDescription = '后端未返回该月的自然日数据',
}: {
  days: CandidateMonthlyDay[]
  conditionByDate?: Record<string, FillingConditionBadge[]>
  effectEvidenceStatus?: EffectEvidenceStatus
  renderCell: (args: {
    day: CandidateMonthlyDay
    row: FillingRow
    badges: FillingConditionBadge[]
    effects: DailySpecialEffect[]
    nodeEffects: PlanningDayEffect[]
  }) => ReactNode
  emptyDescription?: string
}) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const v6NodeFlows = days.some((day) => day.node_flows?.length > 0)
  const allRows = v6NodeFlows ? v6NodeRows(days) : FILLING_ROWS
  const groups = v6NodeFlows ? V6_FILLING_GROUPS : FILLING_GROUPS
  const visibleRows = allRows.filter((row) => !collapsedGroups.has(row.group))
  const groupCounts = new Map<string, number>()
  const groupFirstKey = new Map<string, string>()
  for (const row of visibleRows) {
    groupCounts.set(row.group, (groupCounts.get(row.group) ?? 0) + 1)
    if (!groupFirstKey.has(row.group)) groupFirstKey.set(row.group, row.key)
  }

  const columns: ColumnsType<FillingRow> = [
    {
      title: '车间 / 区段',
      dataIndex: 'group',
      fixed: 'left',
      width: 108,
      onCell: (row) => ({
        rowSpan: groupFirstKey.get(row.group) === row.key ? groupCounts.get(row.group) : 0,
        className: `filling-label filling-group-label${row.sectionEnd ? ' section-end' : ''}`,
      }),
      render: (value: string) => <span className={value === 'WIP 与缓冲' ? 'filling-wip-label' : undefined}>{value}</span>,
    },
    {
      title: '指标',
      dataIndex: 'measure',
      fixed: 'left',
      width: 118,
      onCell: (row) => ({ className: `filling-label${row.sectionEnd ? ' section-end' : ''}` }),
    },
    ...days.map((day) => {
      const badges = conditionByDate[day.date] ?? []
      const legacyMode = effectEvidenceStatus === undefined
      const effects = effectEvidenceStatus === 'NOT_EVALUATED' ? [] : day.special_effects ?? []
      const visibleEffects = effects
        .filter((effect) => effectMeta[effect.type])
        .sort((left, right) => effectMeta[right.type].priority - effectMeta[left.type].priority)
        .slice(0, 2)
      const effectsForRow = (row: FillingRow): PlanningDayEffect[] => (
        effectEvidenceStatus === 'EVALUATED' && row.nodeId
          ? day.effects_by_node?.[row.nodeId] ?? []
          : []
      )
      const scopedClass = (row: FillingRow) => {
        const items = effectsForRow(row)
        if (items.some((item) => item.type === 'SHUTDOWN')) return 'shutdown-cell'
        if (items.some((item) => item.type === 'WORKDAY_RELOCATED_OUT')) return 'shutdown-cell'
        if (items.some((item) => item.type === 'LINE_REFILL')) return 'restart-cell'
        if (items.some((item) => item.type === 'WORKDAY_RELOCATED_IN')) return 'restart-cell'
        if (items.some((item) => item.type === 'CLEARING')) return 'clearing-cell'
        return ''
      }
      return {
        title: (
          <div className={`day-header ${day.calendar_state === 'REST' ? 'rest-day' : ''} ${day.shutdown_day ? 'day-shutdown' : ''} ${day.clearing_day ? 'day-clearing' : ''} ${day.restart_day ? 'day-restart' : ''}`}>
            <span>{day.date.slice(5).replace('-', '/')}</span>
            <small>{formatDate(day.date).split(' ')[1] || formatDate(day.date).slice(-2)}</small>
            <StatusTag value={day.lock_state} short />
            {visibleEffects.map((effect, index) => {
              const meta = effectMeta[effect.type]
              return <span key={`${effect.type}-${index}`} className={meta.className} title={effect.reason || meta.label}>{meta.label}</span>
            })}
            {effects.length === 0 && day.clearing_day && <span className="day-clear-badge" title="停线前清线">清线</span>}
            {effects.length === 0 && day.restart_day && <span className="day-restart-badge" title="停线结束后恢复生产">复线</span>}
            {badges.length > 0 && (
              <span className="day-condition-badges">
                {badges.slice(0, 2).map((badge) => <span key={badge.key} className={`day-condition-badge ${badge.color}`} title={`${badge.label}（${badge.group}）`}>{badge.label}</span>)}
                {badges.length > 2 && <span className="day-condition-badge" title={badges.map((badge) => badge.label).join(' / ')}>+{badges.length - 2}</span>}
              </span>
            )}
          </div>
        ),
        key: day.date,
        width: 84,
        onCell: (row: FillingRow) => ({ className: `${day.calendar_state === 'REST' ? 'rest-cell' : ''} ${day.lock_state === 'LOCKED' ? 'locked-cell' : ''}${legacyMode && day.shutdown_day ? ' shutdown-cell' : ''}${legacyMode && day.clearing_day ? ' clearing-cell' : ''}${legacyMode && day.restart_day ? ' restart-cell' : ''}${scopedClass(row) ? ` ${scopedClass(row)}` : ''}${row.sectionEnd ? ' section-end' : ''}` }),
        render: (_value: unknown, row: FillingRow) => renderCell({ day, row, badges, effects, nodeEffects: effectsForRow(row) }),
      }
    }),
    {
      title: '月度合计',
      key: 'monthly-total',
      fixed: 'right',
      width: 86,
      onCell: (row) => ({ className: row.sectionEnd ? 'section-end' : '' }),
      render: (_value: unknown, row: FillingRow) => {
        const total = rowMonthlyTotal(row, days)
        return <span className={row.total ? 'cell-total' : undefined}>{total === null ? '—' : displayValue(total)}</span>
      },
    },
  ]

  return <>
    <div className="filling-group-controls" data-testid="filling-group-controls">
      <div className="filling-group-buttons">
        <span className="filling-group-caption">分组显示</span>
        {groups.map((group) => {
          const collapsed = collapsedGroups.has(group)
          return <Button key={group} size="small" className={`filling-group-toggle ${collapsed ? 'is-collapsed' : 'is-expanded'}`} aria-pressed={!collapsed} onClick={() => setCollapsedGroups((current) => {
            const next = new Set(current)
            if (next.has(group)) next.delete(group)
            else next.add(group)
            return next
          })}><span aria-hidden>{collapsed ? '▸' : '▾'}</span> {group}</Button>
        })}
      </div>
      <Space size={4}>
        <Button size="small" onClick={() => setCollapsedGroups(new Set())}>展开全部</Button>
        <Button size="small" onClick={() => setCollapsedGroups(new Set(groups))}>收起全部</Button>
      </Space>
    </div>
    {days.length === 0 ? <Empty description={emptyDescription} /> : <FillingMatrix columns={columns} dataSource={visibleRows} />}
  </>
}
