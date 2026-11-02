import { CalendarOutlined, InfoCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Drawer, Empty, List, Row, Space, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { v6Api } from '../../api/v6'
import { BarMetricChart, LineMetricChart } from '../../components/MetricChart'
import { PageState } from '../../components/PageState'
import type {
  V6CandidateAnnualDay,
  V6CandidateAnnualOverview,
  V6FormalAnnualOverview,
  V6HolidayBoundaryNote,
  V6ProjectionViewIdentity,
} from '../../types/v6'
import { AnnualCalendarGrid, type AnnualGridDay } from '../AnnualOverview/AnnualCalendarGrid'
import { AnnualSummaryRail } from '../AnnualOverview/AnnualSummaryRail'
import { MonthlyFactsTable } from '../AnnualOverview/MonthlyFactsTable'
import { SafeHolidayWindowInfo } from './SafeHolidayWindowInfo'
import { displayValue } from '../../utils/format'

function boundaryNoteText(note: V6HolidayBoundaryNote): string {
  if (note.code === 'HORIZON_START_INPUT_PRESERVED') {
    return `计划从停线期开始，期初 ${note.node_id || '车间'} WIP ${note.current_wip ?? '—'} 已按权威输入保留；周期外目标 ${note.target_wip ?? '—'} 不适用。`
  }
  if (note.code === 'DEPENDENCY_REFILL_DELAYED') {
    return `下游 ${note.node_id || 'PS'} 补线因上游 ${note.blocking_workshop_ids?.join('、') || '车间'} 停线延后至 ${note.effective_date || '首个物料可行日'}；目标 ${note.target_wip ?? '—'} 保持不变。`
  }
  if (note.code === 'DEPENDENCY_REFILL_NOT_APPLICABLE') {
    return `下游 ${note.node_id || 'PS'} 补线依赖的上游 ${note.blocking_workshop_ids?.join('、') || '车间'} 持续停线至计划期末，本期不制造周期外目标 ${note.target_wip ?? '—'}。`
  }
  return `停线延伸至计划期末，${note.node_id || '车间'} 的周期外复线目标 ${note.target_wip ?? '—'} 不属于本期排产。`
}

export function CandidateAnnualPanel({
  candidateId,
  issueCount,
  onOpenMonth,
}: {
  candidateId: string
  issueCount: number
  onOpenMonth: (month: string) => void
}) {
  const query = useQuery({
    queryKey: ['v6', 'candidate-annual-overview', candidateId],
    queryFn: () => v6Api.candidateAnnualOverview(candidateId),
    enabled: Boolean(candidateId),
    retry: false,
  })
  if (query.isLoading) return <PageState kind="loading" rows={8} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return <PageState kind="empty" title="后端未提供候选年度总览投影" />
  return <V6AnnualProjectionView
    annual={query.data}
    identity={{ kind: 'CANDIDATE', sourceId: candidateId, revision: query.data.candidate_revision }}
    issueCount={issueCount}
    onOpenMonth={onOpenMonth}
  />
}

export function V6AnnualProjectionView({
  annual,
  identity,
  issueCount,
  onOpenMonth,
}: {
  annual: V6CandidateAnnualOverview | V6FormalAnnualOverview
  identity: V6ProjectionViewIdentity
  issueCount: number
  onOpenMonth: (month: string) => void
}) {
  const [focusDate, setFocusDate] = useState<string | null>(null)
  const typeclassRows = Object.entries(annual.typeclass_facts).map(([typeclassId, facts]) => ({ typeclassId, ...facts }))
  const statusByDate = useMemo(() => {
    const result: Record<string, { mode: string; effects: V6CandidateAnnualDay['special_effects'] }> = {}
    const evaluated = annual.effect_evidence_status === 'EVALUATED'
    for (const day of annual.days || []) {
      result[day.date] = {
        mode: day.working_mode_summary || (day.planned_units > 0 ? 'SHIFT_8H' : 'NO_PRODUCTION'),
        effects: evaluated ? day.special_effects || [] : [],
      }
    }
    return result
  }, [annual])
  const evidenceEvaluated = annual.effect_evidence_status === 'EVALUATED'
  const annualDays: AnnualGridDay[] = annual.days.map((day) => ({
    date: day.date,
    calendar_state: day.calendar_state,
    planned_units: day.planned_units,
    working_mode_summary: day.working_mode_summary,
    lock_state: day.lock_state,
  }))
  const focus = focusDate ? annual.days.find((day) => day.date === focusDate) || null : null
  const focusComposite = focus?.special_effects
    .map((effect) => annual.composite_stop_blocks?.find((item) => item.composite_window_id === effect.window_id))
    .find(Boolean)
  return <div className="candidate-annual-overview annual-overview">
    {!evidenceEvaluated && <Alert type="warning" showIcon message={`${identity.kind === 'FORMAL_PP' ? '该 Formal PP' : '历史 Candidate'} 缺少权威日级事件证据`} description="年度日历不展示推测的清线、停线或复线标记。" style={{ marginBottom: 14 }} />}
    <SafeHolidayWindowInfo evidence={annual.holiday_reconciliation} onOpenMonth={onOpenMonth} />
    {annual.composite_stop_blocks?.length > 0 && <Alert
      type="info"
      showIcon
      style={{ marginBottom: 14 }}
      message="相邻长停线已合并并迁移工作日"
      description={annual.composite_stop_blocks.map((item) => `${item.original_start_date}—${item.original_end_date}：移出 ${item.source_workdays.length} 日，移入 ${item.destination_workdays.join('、')}`).join('；')}
    />}
    {annual.boundary_notes.length > 0 && <Alert
      type="info"
      showIcon
      icon={<InfoCircleOutlined />}
      style={{ marginBottom: 14 }}
      message="计划周期边界按权威输入处理"
      description={<List size="small" dataSource={annual.boundary_notes} renderItem={(note) => <List.Item>{boundaryNoteText(note)}</List.Item>} />}
    />}
    <Row gutter={[14, 14]}>
      <Col xs={24} xl={18}>
        <Card size="small" title={<Space><CalendarOutlined />年度日历与自动停线窗口</Space>}>
          {annualDays.length === 0 ? <Empty description="后端未返回候选日级日历数据" /> : <AnnualCalendarGrid days={annualDays} statusByDate={statusByDate} onSelectDate={setFocusDate} />}
        </Card>
      </Col>
      <Col xs={24} xl={6}>
        <AnnualSummaryRail
          annualPpTotal={Number(annual.annual_pp_total ?? 0)}
          annualPrTotal={Number(annual.annual_pr_total ?? 0)}
          annualClosureGap={Number(annual.annual_closure_gap ?? 0)}
          productionDayCount={Number(annual.production_day_count ?? 0)}
          doubleShiftDays={Number(annual.double_shift_production_days ?? 0)}
          wipDeviation={0}
          issueCount={issueCount}
          status={identity.kind === 'FORMAL_PP' ? 'FORMAL' : 'DRAFT'}
          showWip={false}
        />
      </Col>
    </Row>
    <Row gutter={[14, 14]} style={{ marginTop: 14 }}>
      <Col xs={24} xl={8}><Card size="small" title="年度趋势（按月）"><LineMetricChart months={annual.months} series={[{ key: 'pr_total', label: 'PR总量', color: '#1677ff' }, { key: 'pp_realized', label: 'PP实际计划', color: '#389e0d' }, { key: 'ws_total', label: 'WS总量', color: '#722ed1' }]} /></Card></Col>
      <Col xs={24} xl={8}><Card size="small" title="期末库存趋势（按月）"><BarMetricChart months={annual.months} field="inventory_eom" color="#3478e5" title="期末库存" /></Card></Col>
      <Col xs={24} xl={8}><Card size="small" title="月度事实表"><MonthlyFactsTable months={annual.months} onOpenMonth={onOpenMonth} showWip={false} /></Card></Col>
    </Row>
    <Card size="small" title="车型年度 PR / FOK / gap（后端事实）" style={{ marginTop: 14 }}>
      <Table
        size="small"
        rowKey="typeclassId"
        pagination={false}
        scroll={{ x: 700 }}
        dataSource={typeclassRows}
        locale={{ emptyText: '后端未返回车型年度事实' }}
        columns={[
          { title: '车型', dataIndex: 'typeclassId', width: 110 },
          { title: '年度 PR', dataIndex: 'annual_pr', align: 'right', render: (value: number) => displayValue(value) },
          { title: '年度 FOK（Finish OUT）', dataIndex: 'annual_fok', align: 'right', render: (value: number) => displayValue(value) },
          { title: '年度 gap', dataIndex: 'annual_gap', align: 'right', render: (value: number) => <span className={value === 0 ? 'number-good' : 'number-danger'}>{displayValue(value)}</span> },
          { title: '月度', width: 112, render: () => '展开查看 12 月' },
        ]}
        expandable={{
          rowExpandable: (row) => Object.keys(row.months).length > 0,
          expandedRowRender: (row) => <Table
            size="small"
            rowKey="month"
            pagination={false}
            scroll={{ x: 520 }}
            dataSource={Object.entries(row.months).map(([month, facts]) => ({ month, ...facts }))}
            columns={[
              { title: '月份', dataIndex: 'month', width: 120 },
              { title: 'PR', dataIndex: 'pr', align: 'right', render: (value: number) => displayValue(value) },
              { title: 'FOK（Finish OUT）', dataIndex: 'fok', align: 'right', render: (value: number) => displayValue(value) },
              { title: 'gap', dataIndex: 'gap', align: 'right', render: (value: number) => <span className={value === 0 ? 'number-good' : 'number-danger'}>{displayValue(value)}</span> },
              { title: '操作', width: 112, render: (_value, monthFact) => <Button type="link" size="small" onClick={() => onOpenMonth(monthFact.month)}>打开当月</Button> },
            ]}
          />,
        }}
      />
    </Card>
    <Drawer title={focusDate ? `${focusDate} · ${identity.kind === 'FORMAL_PP' ? '正式 PP' : '候选'}日期详情` : '日期详情'} open={Boolean(focusDate)} onClose={() => setFocusDate(null)} width={520}>
      {focusComposite && <Card size="small" title="复合窗口与工作日迁移" style={{ marginBottom: 12 }}><Typography.Paragraph>
        动态阈值：gap {focusComposite.gap_workdays} ≤ 复线 {focusComposite.refill_required_days} + 清线 {focusComposite.clearing_required_days}<br />
        工作日：{focusComposite.source_workdays.join('、')} → {focusComposite.destination_workdays.join('、')}<br />
        成员窗口：{focusComposite.member_window_ids.join('、')}
      </Typography.Paragraph></Card>}
      {!focus || !evidenceEvaluated || focus.special_effects.length === 0 ? <Empty description="该日没有权威停线、清线或复线事件" /> : <List dataSource={focus.special_effects} renderItem={(effect) => <List.Item><div><Space><Tag color={effect.type === 'SHUTDOWN' ? 'orange' : effect.type === 'LINE_REFILL' ? 'green' : 'blue'}>{effect.type === 'SHUTDOWN' ? '停线' : effect.type === 'CLEARING' ? '清线' : effect.type === 'LINE_REFILL' ? '复线' : effect.type}</Tag><Typography.Text>{effect.node_id} / {effect.quantity_scope === 'NODE_TOTAL' ? `节点总量（触发车型 ${effect.typeclass_id}）` : `车型 ${effect.typeclass_id}`}</Typography.Text></Space><Typography.Paragraph style={{ margin: '8px 0 0' }}>窗口 {effect.window_id ? effect.window_id.slice(0, 8) : '—'} · 事件 {effect.event_id.slice(0, 8)}<br />WIP {effect.wip_bod ?? '—'} → {effect.wip_target ?? '—'} → {effect.wip_eod ?? '—'}<br />{effect.reason}</Typography.Paragraph></div></List.Item>} />}
      {focusDate && <Button type="primary" onClick={() => { onOpenMonth(focusDate.slice(0, 7)); setFocusDate(null) }}>打开当月 Filling</Button>}
    </Drawer>
  </div>
}
