import { useMemo } from 'react'
import { Alert, Button, Card, Collapse, Empty, Space, Table, Tabs, Tag, Typography } from 'antd'
import { ArrowLeftOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import type { V6FormalFacts, V6MonthlyMetric, V6RecordDiff } from '../../types/v6'

const METRICS = [
  { label: 'PR', month: 'pr_by_month', total: 'pr_total', delta: 'pr_total' },
  { label: 'WS', month: 'ws_by_month', total: 'ws_total', delta: 'ws_total' },
  { label: 'PP', month: 'pp_by_month', total: 'pp_total', delta: 'pp_total' },
  { label: 'Yard stock', month: 'yard_stock_by_month', total: 'yard_stock', delta: 'yard_stock' },
  { label: 'Production day', month: 'production_day_by_month', total: 'production_day_count', delta: 'production_day_count' },
  { label: 'Pending day', month: 'pending_day_by_month', total: 'pending_day_count', delta: 'pending_day_count' },
  { label: 'O/T', month: 'overtime_by_month', total: 'overtime_day_count', delta: 'overtime_day_count' },
  { label: 'Potential vol.', month: 'potential_volume_by_month', total: 'potential_volume_total', delta: 'potential_volume_total' },
] as const

function readMonth(value: V6MonthlyMetric | undefined, month: string) {
  if (value === 'NOT_EVALUATED') return 'NOT_EVALUATED'
  return value?.[month] ?? 0
}

function BusinessSection({ title, facts, months, delta, totals }: { title: string; facts: Record<string, V6MonthlyMetric>; months: string[]; delta?: boolean; totals: Record<string, unknown> }) {
  const rows = METRICS.map((metric) => ({ key: metric.label, label: metric.label, values: facts[metric.month], total: totals[delta ? metric.delta : metric.total] }))
  return <Card className={`v6-business-section ${delta ? 'delta' : ''}`} title={title}>
    <Table size="small" pagination={false} rowKey="key" scroll={{ x: 1180 }} dataSource={rows} columns={[
      { title: delta ? 'Dev. · 新 − 旧' : '指标', dataIndex: 'label', width: 170, fixed: 'left', render: (value) => <strong>{value}</strong> },
      ...months.map((month) => ({ title: month.slice(5), width: 76, align: 'right' as const, render: (_: unknown, row: any) => { const value = readMonth(row.values, month); return delta && typeof value === 'number' ? <span className={value > 0 ? 'v6-delta-positive' : value < 0 ? 'v6-delta-negative' : ''}>{value > 0 ? `+${value}` : value}</span> : String(value) } })),
      { title: 'TTL.', width: 100, fixed: 'right' as const, align: 'right' as const, dataIndex: 'total', render: (value) => delta && typeof value === 'number' ? <strong className={value > 0 ? 'v6-delta-positive' : value < 0 ? 'v6-delta-negative' : ''}>{value > 0 ? `+${value}` : value}</strong> : <strong>{String(value ?? '—')}</strong> },
    ]} />
  </Card>
}

const INPUT_LABELS: Record<string, string> = {
  pr_version_id: 'PR 版本',
  ws_version_id: 'WS 版本',
  factory_version_id: '工厂模型',
  calendar_version_id: '生产日历',
  initial_state_version_id: '期初状态',
  wip_policy_version_id: 'WIP 策略',
  actual_revision_id: 'Actual 版本',
}

function displayScalar(value: unknown) {
  if (value === null || value === undefined || value === '') return <Typography.Text type="secondary">—</Typography.Text>
  if (typeof value === 'boolean') return <Tag color={value ? 'success' : 'default'}>{value ? '是' : '否'}</Tag>
  if (typeof value === 'string' || typeof value === 'number') return <Typography.Text code>{String(value)}</Typography.Text>
  return <Typography.Text>{JSON.stringify(value)}</Typography.Text>
}

function TechnicalDetails({ value }: { value: unknown }) {
  return <Collapse ghost size="small" className="v6-technical-details" items={[{
    key: 'raw',
    label: '技术详情',
    children: <pre className="v6-json-preview">{JSON.stringify(value, null, 2)}</pre>,
  }]} />
}

function InputDiffPanel({ value }: { value: Record<string, { before: unknown; after: unknown }> }) {
  const rows = Object.entries(value).map(([field, diff]) => ({ field, ...diff }))
  if (!rows.length) return <Card className="v6-diff-card"><Empty description="输入版本没有变化" /></Card>
  return <Card className="v6-diff-card" title="输入版本变更">
    <Table size="small" pagination={false} rowKey="field" dataSource={rows} columns={[
      { title: '输入项', dataIndex: 'field', width: 180, render: (field) => <strong>{INPUT_LABELS[field] || field}</strong> },
      { title: '旧版本', dataIndex: 'before', render: displayScalar },
      { title: '新版本', dataIndex: 'after', render: displayScalar },
    ]} />
    <TechnicalDetails value={value} />
  </Card>
}

function recordTitle(value: Record<string, unknown>) {
  return String(value.plugin_type || value.kind || value.code || value.warning_code || value.selector_id || value.typeclass_id || '业务记录')
}

function recordScope(value: Record<string, unknown>) {
  const scope = (value.scope || {}) as Record<string, unknown>
  const start = scope.start_date || value.start_date
  const end = scope.end_date || value.end_date
  const workshops = scope.workshop_ids || value.workshop_id
  return [start && end ? `${start} → ${end}` : start || end, workshops].filter(Boolean).map(String).join(' · ') || '全局'
}

function RecordDiffSection({ title, tone, rows }: { title: string; tone: string; rows: Record<string, unknown>[] }) {
  return <Card size="small" className={`v6-diff-section ${tone}`} title={<Space><span>{title}</span><Tag>{rows.length}</Tag></Space>}>
    {rows.length ? <Table size="small" pagination={false} rowKey={(_row, index) => `${title}-${index}`} dataSource={rows} columns={[
      { title: '对象', render: (_, row) => <strong>{recordTitle(row)}</strong> },
      { title: '作用域', render: (_, row) => recordScope(row) },
    ]} /> : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={`没有${title}项`} />}
  </Card>
}

function RecordDiffPanel({ title, value }: { title: string; value: V6RecordDiff }) {
  const changed = value.changed.map((item) => ({
    ...item.after,
    __before: item.before,
    __after: item.after,
  }))
  return <div className="v6-diff-panel">
    <div className="v6-diff-panel-head"><strong>{title}</strong><Typography.Text type="secondary">新增、移除与修改分别列示</Typography.Text></div>
    <div className="v6-diff-grid">
      <RecordDiffSection title="新增" tone="added" rows={value.added} />
      <RecordDiffSection title="移除" tone="removed" rows={value.removed} />
      <RecordDiffSection title="修改" tone="changed" rows={changed} />
    </div>
    <TechnicalDetails value={value} />
  </div>
}

function HolidayWipDiffPanel({ holiday, wip }: { holiday: V6RecordDiff; wip: Record<string, number> }) {
  const wipRows = Object.entries(wip).map(([node, delta]) => ({ node, delta }))
  return <div className="v6-diff-panel">
    <RecordDiffPanel title="假期窗口变化" value={holiday} />
    <Card className="v6-diff-card" title="WIP 节点变化">
      <Table size="small" pagination={false} rowKey="node" dataSource={wipRows} columns={[
        { title: '节点', dataIndex: 'node', render: (value) => <strong>{value}</strong> },
        { title: 'Dev. · 新 − 旧', dataIndex: 'delta', align: 'right', render: (value: number) => <Tag color={value > 0 ? 'blue' : value < 0 ? 'red' : 'default'}>{value > 0 ? `+${value}` : value}</Tag> },
      ]} />
      {!wipRows.length && <Empty description="没有 WIP 节点变化" />}
      <TechnicalDetails value={wip} />
    </Card>
  </div>
}

export function V6FormalCompare() {
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const oldId = params.get('old') || ''
  const newId = params.get('new') || ''
  const query = useQuery({ queryKey: ['v6', 'formal', 'compare', oldId, newId], queryFn: () => v6Api.compareFormal(oldId, newId), enabled: Boolean(oldId && newId), retry: false })
  const months = useMemo(() => {
    const facts = query.data?.formal_versions || []
    const keys = facts.flatMap((item) => Object.keys(item.pr_by_month || {})).sort()
    const year = keys[0]?.slice(0, 4) || String(new Date().getFullYear())
    return Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, '0')}`)
  }, [query.data])
  if (!oldId || !newId) return <PageState kind="business-blocked" title="缺少比较版本" reasons={['请从正式 PP 库选择旧版本和新版本']} action={<Button onClick={() => navigate('/v6/formal-pp')}>返回正式 PP 库</Button>} />
  if (query.isLoading) return <PageState kind="loading" rows={10} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  const result = query.data
  if (!result || result.formal_versions.length !== 2 || result.comparisons.length !== 1) return <PageState kind="business-blocked" title="后端没有返回固定两个版本的比较结果" reasons={['比较页不会自行拼造缺失数据']} />
  const oldFacts = result.formal_versions[0] as V6FormalFacts
  const newFacts = result.formal_versions[1] as V6FormalFacts
  const comparison = result.comparisons[0]
  const monthFacts = (facts: V6FormalFacts) => Object.fromEntries(METRICS.map((metric) => [metric.month, facts[metric.month] as V6MonthlyMetric]))
  return <div className="page-container v6-formal-compare-page">
    <PageHeader title="正式 PP 比较" subtitle="业务方向固定：上旧、下新，Dev. = 新版本 − 旧版本" actions={<Button icon={<ArrowLeftOutlined />} onClick={() => navigate('/v6/formal-pp')}>返回正式 PP 库</Button>} />
    <Alert type="info" showIcon message={<span>旧版本 <Tag>{oldFacts.display_name}</Tag> → 新版本 <Tag color="blue">{newFacts.display_name}</Tag></span>} description="八项业务指标全部按 Jan.–Dec. 与 TTL. 比较；未评估值不会转换为 0。" style={{ marginBottom: 14 }} />
    <Tabs items={[
      { key: 'matrix', label: '月度业务矩阵', children: <div className="v6-business-stack"><BusinessSection title={`旧 · ${oldFacts.display_name}`} facts={monthFacts(oldFacts)} months={months} totals={oldFacts as unknown as Record<string, unknown>} /><BusinessSection title={`新 · ${newFacts.display_name}`} facts={monthFacts(newFacts)} months={months} totals={newFacts as unknown as Record<string, unknown>} /><BusinessSection title="Dev. · 新 − 旧" delta facts={comparison.monthly_delta} months={months} totals={comparison.delta} /></div> },
      { key: 'inputs', label: `输入版本 (${comparison.changed_inputs.length})`, children: <InputDiffPanel value={comparison.input_diff} /> },
      { key: 'conditions', label: '排产条件', children: <Space direction="vertical" size="large" style={{ width: '100%' }}><RecordDiffPanel title="输入条件变化" value={comparison.condition_diff} /><RecordDiffPanel title="条件执行结果变化" value={comparison.condition_result_diff} /></Space> },
      { key: 'holiday', label: '假期 / WIP', children: <HolidayWipDiffPanel holiday={comparison.holiday_window_diff} wip={comparison.wip_delta} /> },
      { key: 'warnings', label: '问题 / 警告', children: <RecordDiffPanel title="问题与警告变化" value={comparison.warning_diff} /> },
    ]} />
  </div>
}
