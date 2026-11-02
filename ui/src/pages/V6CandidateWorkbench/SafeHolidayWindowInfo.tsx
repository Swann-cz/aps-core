import { Alert, Button, List, Space, Tag, Typography } from 'antd'
import type { V6HolidayReconciliationEvidence, V6IssueWindowSummary, V6WindowLineage } from '../../types/v6'

function windowText(window: V6IssueWindowSummary | null): string {
  if (!window) return '—'
  const dates = window.start_date === window.end_date
    ? window.start_date
    : `${window.start_date || '—'} 至 ${window.end_date || '—'}`
  return [dates, window.workshop_id, window.typeclass_id ? `车型 ${window.typeclass_id}` : null]
    .filter(Boolean)
    .join(' · ')
}

function relevantLineages(evidence: V6HolidayReconciliationEvidence): V6WindowLineage[] {
  const source = evidence.window_change_notice?.lineage
    ?? evidence.final_semantic_diff?.requires_clearing_lineage
    ?? []
  return source.filter((item) =>
    item.causing_opened_dates.length > 0
    || !['NONCORE_STABLE', 'CORE_STABLE'].includes(item.classification),
  )
}

export function hasSafeWindowInformation(evidence: V6HolidayReconciliationEvidence | null): boolean {
  if (!evidence) return false
  if (evidence.window_change_notice?.status === 'INFORMATIONAL') return true
  return Boolean(
    (evidence.opened_activity_days?.length ?? 0) > 0
    && evidence.wip_trajectory_unchanged === true
    && evidence.final_semantic_diff?.blocking === false,
  )
}

export function SafeHolidayWindowInfo({
  evidence,
  onOpenMonth,
}: {
  evidence: V6HolidayReconciliationEvidence | null
  onOpenMonth?: (month: string) => void
}) {
  if (!evidence || !hasSafeWindowInformation(evidence)) return null
  const opened = evidence.window_change_notice?.opened_activity_days
    ?? evidence.opened_activity_days
    ?? []
  const openedDates = Array.from(new Set(opened.map((item) => item.date))).sort()
  const months = Array.from(new Set(openedDates.map((date) => date.slice(0, 7))))
  const lineages = relevantLineages(evidence)
  const sharedWipApplied = evidence.shared_wip_reconciliation?.status === 'APPLIED'
  return <Alert
    type="info"
    showIcon
    style={{ marginBottom: 14 }}
    message="受控开工导致停线窗口重新识别，已通过语义校验"
    description={<div>
      <Typography.Paragraph style={{ marginBottom: 8 }}>
        开工日期：{opened.map((item) => `${item.date}（${item.planned_out}）`).join('、') || '—'}。{sharedWipApplied ? '窗口拆分已通过语义校验；共享WIP协调保持了年度产量、焊装WIP和最终节点目标。' : 'WIP轨迹未改变。'}无需再次重排，本信息不影响保存。
      </Typography.Paragraph>
      {lineages.length > 0 && <List
        size="small"
        dataSource={lineages}
        renderItem={(item) => <List.Item>
          <div>
            <Space wrap><Tag color="blue">{item.classification}</Tag><span>{windowText(item.ancestor)}</span></Space>
            <div className="muted">拆分后：{item.fragments.map(windowText).join('；') || windowText(item.descendant)}</div>
            <div className="muted">受控开工：{item.causing_opened_dates.join('、') || '—'}</div>
          </div>
        </List.Item>}
      />}
      {onOpenMonth && months.length > 0 && <Space wrap>
        {months.map((month) => <Button key={month} size="small" onClick={() => onOpenMonth(month)}>查看 {month} Filling</Button>)}
      </Space>}
    </div>}
  />
}
