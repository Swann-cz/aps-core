import { Button, Empty, Space } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useState } from 'react'
import { capText, conditionNames, modeName, phaseName, quantity, type MonthlyDay, type MonthlyView } from '../../api/core'
import { FillingMatrix } from './FillingMatrix'
import { phaseBadge, phaseLabels } from '../../utils/corePhase'

type Row = {
  key: string; group: string; measure: string; total?: boolean; model?: boolean
  read: (day: MonthlyDay) => string | number
  modelRows?: Row[]
}

function rowsFor(view: MonthlyView): Row[] {
  const rows: Row[] = [
    { key: 'mode', group: '生产参数', measure: '模式', read: d => modeName(d.mode_summary) },
    { key: 'hours', group: '生产参数', measure: '小时', read: d => d.hours_max },
  ]
  for (const node of ['BS1', 'BS2']) {
    for (const [field, label] of [['in', '投入'], ['in_cum', '投入累计'], ['out', '产出'], ['out_cum', '产出累计']] as const) {
      rows.push({ key: `${node}-${field}`, group: '焊装 Body Shop', measure: `${node} ${label}`, total: field === 'in' || field === 'out', read: d => d.workshops[node][field] })
    }
  }
  for (const [node, group] of [['WBS', 'WBS 缓冲区'], ['PS', '涂装 Paint Shop'], ['PBS', 'PBS 缓冲区'], ['AS_MAIN', '总装主线'], ['AS_FIN', '总装完成线']]) {
    const flow = (d: MonthlyDay) => node === 'WBS' || node === 'PBS' ? d.buffers[node] : d.workshops[node]
    for (const [field, label] of [['bod', '日初'], ['in', '投入'], ['out', node === 'AS_FIN' ? 'FOK（产出）' : '产出'], ['eod', `日末（目标 ${quantity(view.targets[node])}；${capText(view.caps[node])}）`]] as const) {
      const total = field === 'in' || field === 'out'
      rows.push({
        key: `${node}-${field}`, group, measure: label, total, read: d => flow(d)[field],
        ...(field === 'bod' ? {} : { modelRows: view.models.map(model => ({
          key: `${node}-${field}-${model}`, group, measure: `车型 ${model}`, model: true, total,
          read: (d: MonthlyDay) => flow(d).by_model[model][field],
        })) }),
      })
    }
  }
  for (const node of ['BS1', 'BS2']) rows.push({ key: `${node}-eod`, group: '在制与成品', measure: `${node} 日末（目标 ${quantity(view.targets[node])}；${capText(view.caps[node])}）`, read: d => d.workshops[node].eod })
  for (const [field, label] of [['ws', '交付（WS）'], ['eod', '成品库存'], ['bl', '欠交']] as const) rows.push({ key: `fin-${field}`, group: '在制与成品', measure: label, total: field === 'ws', read: d => d.fin[field] })
  return rows
}

export function CoreFillingBusinessView({ view }: { view: MonthlyView }) {
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set())
  const [expandedRows, setExpandedRows] = useState<Set<string>>(() => new Set())
  const allRows = rowsFor(view)
  const groups = Array.from(new Set(allRows.map(row => row.group)))
  const visibleRows = allRows.filter(row => !collapsedGroups.has(row.group)).flatMap(row => [row, ...(expandedRows.has(row.key) ? row.modelRows ?? [] : [])])
  const toggleRow = (key: string) => setExpandedRows(current => {
    const next = new Set(current)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    return next
  })
  const sectionEnd = (row: Row) => visibleRows[visibleRows.indexOf(row) + 1]?.group !== row.group ? 'section-end' : ''
  const columns: ColumnsType<Row> = [
    {
      title: '区段', dataIndex: 'group', fixed: 'left', width: 108,
      onCell: row => ({ rowSpan: visibleRows.find(item => item.group === row.group) === row ? visibleRows.filter(item => item.group === row.group).length : 0, className: 'filling-label filling-group-label section-end' }),
    },
    {
      title: '指标', dataIndex: 'measure', fixed: 'left', width: 270,
      onCell: row => ({ className: `filling-label ${sectionEnd(row)}` }),
      render: (value: string, row) => row.modelRows ? <Button type="text" size="small" className="core-filling-expand" aria-expanded={expandedRows.has(row.key)} aria-label={`${row.group} ${value}车型明细`} onClick={() => toggleRow(row.key)}><span aria-hidden>{expandedRows.has(row.key) ? '▾' : '▸'}</span>{value}</Button> : <span className={row.model ? 'core-filling-model' : undefined}>{value}</span>,
    },
    ...view.days.map(day => {
      const phases = day.phase.split('+').filter(phase => phase !== 'NORMAL')
      const color = phases.includes('STOP') ? 'shutdown-cell' : phases.includes('BS_CLEAR') ? 'clearing-cell' : phases.includes('REFILL') ? 'restart-cell' : !day.is_working_capable ? 'rest-cell' : ''
      const conditionsTitle = day.conditions.map(condition => `${condition.id}：${conditionNames[condition.type]}`).join('；')
      return {
        key: day.date, width: 84,
        title: <div className={`day-header ${!day.is_working_capable ? 'rest-day' : ''}`}>
          <span>{day.date.slice(5).replace('-', '/')}</span>
          <small>{['周日', '周一', '周二', '周三', '周四', '周五', '周六'][new Date(`${day.date}T00:00:00`).getDay()]}</small>
          {phases.map(phase => <span key={phase} className={phaseBadge(phase)} title={phaseName(phase)}>{phaseLabels[phase]}</span>)}
          {day.conditions.length > 0 && <span className="day-condition-badges" title={conditionsTitle}>
            {day.conditions.slice(0, 2).map(condition => <span key={condition.id} className="day-condition-badge blue">{conditionNames[condition.type]}</span>)}
            {day.conditions.length > 2 && <span className="day-condition-badge">+{day.conditions.length - 2}</span>}
          </span>}
        </div>,
        onHeaderCell: () => ({ className: color }),
        onCell: (row: Row) => ({ className: `${color} ${sectionEnd(row)}` }),
        render: (_: unknown, row: Row) => { const value = row.read(day); return typeof value === 'number' ? quantity(value) : value },
      }
    }),
    {
      title: '月度合计', key: 'monthly-total', fixed: 'right', width: 86,
      onCell: row => ({ className: sectionEnd(row) }),
      render: (_: unknown, row) => row.total ? <span className="cell-total">{quantity(view.days.reduce((sum, day) => sum + (row.read(day) as number), 0))}</span> : '—',
    },
  ]
  return <div className="core-filling-view">
    <div className="filling-group-controls" data-testid="filling-group-controls">
      <div className="filling-group-buttons">
        <span className="filling-group-caption">分组显示</span>
        {groups.map(group => <Button key={group} size="small" className={`filling-group-toggle ${collapsedGroups.has(group) ? 'is-collapsed' : 'is-expanded'}`} aria-pressed={!collapsedGroups.has(group)} onClick={() => setCollapsedGroups(current => {
          const next = new Set(current)
          if (next.has(group)) next.delete(group)
          else next.add(group)
          return next
        })}><span aria-hidden>{collapsedGroups.has(group) ? '▸' : '▾'}</span> {group}</Button>)}
      </div>
      <Space size={4}>
        <Button size="small" onClick={() => setCollapsedGroups(new Set())}>展开全部</Button>
        <Button size="small" onClick={() => setCollapsedGroups(new Set(groups))}>收起全部</Button>
      </Space>
    </div>
    {view.days.length === 0 ? <Empty description="后端未返回该月的自然日数据" /> : <FillingMatrix columns={columns} dataSource={visibleRows} />}
  </div>
}
