import { LeftOutlined, PlusOutlined, RightOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Descriptions, Drawer, Empty, List, Select, Space, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { v6Api } from '../../api/v6'
import { PageState } from '../../components/PageState'
import type { PlanningDayEffect, ScalarValue } from '../../types/api'
import { displayValue } from '../../utils/format'
import { FillingBusinessView, readFillingRowValue, type CandidateMonthlyDay, type FillingRow } from '../MonthlyFilling/FillingBusinessView'
import type {
  V6CandidateMonthlyFilling,
  V6FormalMonthlyFilling,
  V6ProjectionViewIdentity,
} from '../../types/v6'

const effectLabels: Record<string, string> = {
  SHUTDOWN: '停线',
  CLEARING: '清线',
  LINE_REFILL: '复线',
  CONDITION_EFFECT: '条件影响',
  BOUNDARY_NOTICE: '周期边界提示',
  WINDOW_MERGED: '长停线合并',
  WORKDAY_RELOCATED_OUT: '工作日移出',
  WORKDAY_RELOCATED_IN: '工作日移入',
}

type SelectedDayEvidence = {
  day: CandidateMonthlyDay
  row: FillingRow
  value: ScalarValue
  effects: PlanningDayEffect[]
  source: 'special_effects' | 'effects_by_node'
}

export function CandidateFillingPanel({
  candidateId,
  candidateRevision,
  months,
  requestedMonth,
  onRequestedMonthHandled,
  onSpecifyOutput,
}: {
  candidateId: string
  candidateRevision: number
  months: string[]
  requestedMonth?: string | null
  onRequestedMonthHandled?: () => void
  onSpecifyOutput?: () => void
}) {
  const [month, setMonth] = useState(months[0] || '')
  useEffect(() => {
    if (requestedMonth && months.includes(requestedMonth)) {
      setMonth(requestedMonth)
      onRequestedMonthHandled?.()
    } else if (!months.includes(month)) {
      setMonth(months[0] || '')
    }
  }, [month, months, onRequestedMonthHandled, requestedMonth])
  const query = useQuery({
    queryKey: ['v6', 'candidate-monthly-filling', candidateId, month],
    queryFn: () => v6Api.candidateMonthlyFilling(candidateId, month),
    enabled: Boolean(candidateId && month),
    retry: false,
  })
  if (query.isLoading) return <PageState kind="loading" rows={8} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return <PageState kind="empty" title="后端未提供候选月度 Filling 投影" />
  return <V6FillingProjectionView
    filling={query.data}
    identity={{ kind: 'CANDIDATE', sourceId: candidateId, revision: candidateRevision }}
    months={months}
    month={month}
    onMonthChange={setMonth}
    onSpecifyOutput={onSpecifyOutput}
  />
}

export function V6FillingProjectionView({
  filling,
  identity,
  months,
  month,
  onMonthChange,
  onSpecifyOutput,
}: {
  filling: V6CandidateMonthlyFilling | V6FormalMonthlyFilling
  identity: V6ProjectionViewIdentity
  months: string[]
  month: string
  onMonthChange: (month: string) => void
  onSpecifyOutput?: () => void
}) {
  const [selectedEvidence, setSelectedEvidence] = useState<SelectedDayEvidence | null>(null)
  const moveMonth = (offset: number) => {
    const next = months[months.indexOf(month) + offset]
    if (next) onMonthChange(next)
  }
  const evidenceStatus = filling.effect_evidence_status ?? 'NOT_EVALUATED'
  const selectedComposite = selectedEvidence?.effects
    .map((effect) => filling.composite_stop_blocks?.find((item) => item.composite_window_id === effect.window_id))
    .find(Boolean)
  return <div className="candidate-filling-panel filling-page">
    {evidenceStatus === 'NOT_EVALUATED' && <Alert type="warning" showIcon message={`${identity.kind === 'FORMAL_PP' ? '该 Formal PP' : '历史 Candidate'} 缺少权威日级事件证据`} description="清线、停线、复线标记不展示。" style={{ marginBottom: 12 }} />}
    {filling.composite_stop_blocks?.length > 0 && <Alert type="info" showIcon message="相邻长停线已合并" description={`已形成 ${filling.composite_stop_blocks.length} 个复合窗口；中间工作日移至停线尾部重新排产。`} style={{ marginBottom: 12 }} />}
    <Card className="filling-toolbar" variant="borderless">
      <Space wrap>
        <span>月份</span>
        <Select value={month} options={months.map((value) => ({ value, label: value }))} onChange={onMonthChange} style={{ width: 132 }} />
        <Button icon={<LeftOutlined />} onClick={() => moveMonth(-1)} disabled={months.indexOf(month) <= 0}>上一个月</Button>
        <Button icon={<RightOutlined />} onClick={() => moveMonth(1)} disabled={months.indexOf(month) >= months.length - 1}>下一个月</Button>
        <Tag color="green">自然日</Tag>
        {identity.kind === 'CANDIDATE'
          ? <Tag>{onSpecifyOutput ? '当前候选' : '只读候选'} Draft #{identity.revision}</Tag>
          : <><Tag color="blue">V6.1.4 正式 PP · 只读</Tag><Tag>{identity.displayName}</Tag></>}
        {identity.kind === 'CANDIDATE' && onSpecifyOutput && <Button type="primary" icon={<PlusOutlined />} onClick={onSpecifyOutput}>指定产量</Button>}
        {identity.kind === 'CANDIDATE' && onSpecifyOutput && <Typography.Text type="secondary">指定产量进入统一排产条件，预览后一次性重排。</Typography.Text>}
      </Space>
    </Card>
    <Alert
      type="info"
      showIcon
      message="车型级缓冲、PS、双 AS 投影与 FOK 口径"
      description="WBS、PS、PBS、AS Mainline、AS Finish Line 的合计及各车型 BOD、IN、OUT、EOD 均直接读取后端 node_flows；休息日显示真实 0 与 WIP 结转，AS Finish Line 的 OUT 明确为 FOK，不由前端推算。"
      style={{ marginBottom: 12 }}
    />
    <Card className="filling-card" title={<span>月度 Filling 矩阵（共享业务组件）<small className="muted">当前页读取 {identity.kind === 'FORMAL_PP' ? 'FormalPPVersion 冻结快照' : 'DraftCandidate 后端投影'}，不混用 V5 PlanVersion</small></span>}>
      <FillingBusinessView
        days={filling.days}
        effectEvidenceStatus={evidenceStatus}
        renderCell={({ day, row, effects, nodeEffects }) => {
          if (row.conditionMarker) {
            const labels = effects.map((effect) => effectLabels[effect.type] || effect.type)
            const dayEffects = effects.filter((effect): effect is PlanningDayEffect => 'event_id' in effect)
            return <button
              className="matrix-cell"
              data-testid={`candidate-cell-${row.key}-${day.date}`}
              title={labels.join(' / ') || '该日没有权威事件'}
              onClick={() => setSelectedEvidence({ day, row, value: labels.join(' / ') || null, effects: dayEffects, source: 'special_effects' })}
            >{labels.length ? labels.join(' / ') : '—'}</button>
          }
          const value = readFillingRowValue(day, row)
          const effectDetail = nodeEffects.map((effect) => [
            `${effect.type} · ${effect.node_id}/${effect.quantity_scope === 'NODE_TOTAL' ? `节点总量（触发车型${effect.typeclass_id}）` : effect.typeclass_id}`,
            effect.window_id ? `窗口 ${effect.window_id}` : '',
            `WIP ${effect.wip_bod ?? '—'} → ${effect.wip_target ?? '—'} → ${effect.wip_eod ?? '—'}`,
            effect.reason || '',
          ].filter(Boolean).join(' · ')).join('\n')
          return <button
            className="matrix-cell"
            data-testid={`candidate-cell-${row.key}-${day.date}`}
            title={effectDetail || `当前 ${identity.kind === 'FORMAL_PP' ? 'FormalPPVersion' : 'DraftCandidate'} 的后端只读事实`}
            onClick={() => setSelectedEvidence({ day, row, value, effects: nodeEffects, source: 'effects_by_node' })}
          >{displayValue(value)}</button>
        }}
      />
    </Card>
    <Drawer
      title="日级事件证据"
      width={640}
      open={selectedEvidence !== null}
      onClose={() => setSelectedEvidence(null)}
    >
      {selectedEvidence && <div data-testid="candidate-day-evidence-drawer">
        <Descriptions bordered size="small" column={1}>
          <Descriptions.Item label={identity.kind === 'FORMAL_PP' ? '正式 PP' : '候选'}>{identity.kind === 'FORMAL_PP' ? `${identity.displayName} · ${identity.sourceId}` : `${identity.sourceId} · rev.${identity.revision}`}</Descriptions.Item>
          <Descriptions.Item label="日期">{selectedEvidence.day.date}</Descriptions.Item>
          <Descriptions.Item label="指标 / 节点">{selectedEvidence.row.measure} / {selectedEvidence.row.nodeId ?? '—'}</Descriptions.Item>
          <Descriptions.Item label="显示值">{displayValue(selectedEvidence.value)}</Descriptions.Item>
          <Descriptions.Item label="证据来源">{identity.kind === 'FORMAL_PP' ? 'FormalPPVersion frozen monthly-filling' : 'DraftCandidate monthly-filling'} · {selectedEvidence.source}</Descriptions.Item>
        </Descriptions>
        {selectedComposite && <Card size="small" title="复合窗口与工作日迁移" style={{ marginTop: 16 }}>
          <Descriptions size="small" column={1}>
            <Descriptions.Item label="复合窗口">{selectedComposite.composite_window_id}</Descriptions.Item>
            <Descriptions.Item label="原窗口">{selectedComposite.original_start_date} → {selectedComposite.original_end_date}</Descriptions.Item>
            <Descriptions.Item label="动态阈值">gap {selectedComposite.gap_workdays} ≤ 复线 {selectedComposite.refill_required_days} + 清线 {selectedComposite.clearing_required_days}</Descriptions.Item>
            <Descriptions.Item label="成员窗口">{selectedComposite.member_window_ids.join('、')}</Descriptions.Item>
            <Descriptions.Item label="工作日迁移">{selectedComposite.source_workdays.join('、')} → {selectedComposite.destination_workdays.join('、')}</Descriptions.Item>
            <Descriptions.Item label="越过原结束日">{selectedComposite.extended_beyond_original_end ? '是' : '否'}</Descriptions.Item>
          </Descriptions>
        </Card>}
        {selectedEvidence.effects.length === 0
          ? <Empty description="该日期与节点没有权威日级事件；未根据数值变化推断事件。" style={{ marginTop: 32 }} />
          : <List
            style={{ marginTop: 16 }}
            dataSource={selectedEvidence.effects}
            renderItem={(effect) => <List.Item key={effect.event_id}>
              <Card size="small" style={{ width: '100%' }} title={<Space><Tag color="blue">{effectLabels[effect.type] || effect.type}</Tag><Typography.Text>{effect.phase}</Typography.Text></Space>}>
                <Descriptions size="small" column={1}>
                  <Descriptions.Item label="事件 ID">{effect.event_id}</Descriptions.Item>
                  <Descriptions.Item label="窗口">{effect.window_id ?? '—'}</Descriptions.Item>
                  <Descriptions.Item label="节点 / 数量作用域">{effect.node_kind} / {effect.node_id} / {effect.quantity_scope === 'NODE_TOTAL' ? `节点总量（触发车型 ${effect.typeclass_id}）` : `车型 ${effect.typeclass_id}`}</Descriptions.Item>
                  <Descriptions.Item label="WIP（期初 → 目标 → 期末）"><Typography.Text strong>{effect.wip_bod ?? '—'}</Typography.Text> → <Typography.Text strong>{effect.wip_target ?? '—'}</Typography.Text> → <Typography.Text strong>{effect.wip_eod ?? '—'}</Typography.Text></Descriptions.Item>
                  <Descriptions.Item label="计划 IN / OUT">{effect.planned_in} / {effect.planned_out}</Descriptions.Item>
                  <Descriptions.Item label="来源条件">{effect.source_condition_ids.length ? effect.source_condition_ids.join('、') : '—'}</Descriptions.Item>
                  <Descriptions.Item label="业务原因">{effect.reason || '—'}</Descriptions.Item>
                  <Descriptions.Item label="溯源">monthly-filling event · {effect.event_id}</Descriptions.Item>
                </Descriptions>
              </Card>
            </List.Item>}
          />}
      </div>}
    </Drawer>
    <div className="filling-footer"><span>数据来源：V6 {identity.kind === 'FORMAL_PP' ? 'FormalPPVersion 冻结投影' : 'DraftCandidate 月度投影'}</span><span>{identity.kind === 'FORMAL_PP' ? `正式 PP：${identity.displayName}` : `候选：${identity.sourceId.slice(0, 8)} · rev.${identity.revision}`}</span><span>WBS / PS / PBS / AS WIP 已在对应节点组显示车型 BOD 与 EOD</span></div>
  </div>
}
