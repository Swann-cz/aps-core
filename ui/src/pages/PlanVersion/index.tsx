import { AuditOutlined, ApartmentOutlined, CheckCircleOutlined, ClockCircleOutlined, FileSearchOutlined, LinkOutlined, SafetyOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Collapse, Empty, Row, Space, Table, Tag, Typography, message } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/planning'
import { ApiError } from '../../api/client'
import { QueryError, QueryLoading } from '../../components/ApiState'
import { PageHeader } from '../../components/PageHeader'
import { StatusTag } from '../../components/StatusTag'
import { usePlanning } from '../../app/PlanningContext'
import type { ChoiceTree, ChoiceTreeNode, PlanHistory } from '../../types/api'
import { formatDateTime, shortId } from '../../utils/format'
import { ConfirmationPanel } from './ConfirmationPanel'
import { SessionPath } from './SessionPath'

export function PlanVersion() {
  const planning = usePlanning()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selected, setSelected] = useState<string[]>([])
  const [confirming, setConfirming] = useState(false)
  const [decisionFocus, setDecisionFocus] = useState<string | null>(null)
  const historyQuery = useQuery({
    queryKey: ['plan-history', planning.session_id],
    queryFn: () => api.planHistory(planning.session_id as string),
    enabled: Boolean(planning.session_id),
    staleTime: 30_000,
  })
  // Epic C: backend-owned choice tree (constitution §218 renderer input).
  const choiceTreeQuery = useQuery({
    queryKey: ['choice-tree', planning.session_id],
    queryFn: () => api.choiceTree(planning.session_id as string),
    enabled: Boolean(planning.session_id),
    staleTime: 30_000,
  })
  const healthQuery = useQuery({
    queryKey: ['plan-health', planning.current_plan_version_id],
    queryFn: () => api.planHealth(planning.current_plan_version_id as string),
    enabled: Boolean(planning.current_plan_version_id),
    staleTime: 30_000,
  })
  const confirmationGateQuery = useQuery({
    queryKey: ['confirmation-gate', planning.current_plan_version_id],
    queryFn: () => api.confirmationGate(planning.current_plan_version_id as string),
    enabled: Boolean(planning.current_plan_version_id),
    staleTime: 30_000,
  })
  const profileQuery = useQuery({
    queryKey: ['algorithm-profile', planning.current_plan_version_id],
    queryFn: () => api.algorithmProfile(planning.current_plan_version_id as string),
    enabled: Boolean(planning.current_plan_version_id),
    staleTime: 30_000,
  })

  const current = useMemo(() => historyQuery.data?.find((item) => item.plan_version_id === planning.current_plan_version_id) || historyQuery.data?.[0], [historyQuery.data, planning.current_plan_version_id])
  const decisionLogNode = useMemo(
    () => historyQuery.data?.find((item) => item.plan_version_id === (decisionFocus || planning.current_plan_version_id)) || current,
    [historyQuery.data, decisionFocus, planning.current_plan_version_id, current],
  )
  if (planning.workbench_loading || historyQuery.isLoading || healthQuery.isLoading || confirmationGateQuery.isLoading || profileQuery.isLoading) return <QueryLoading />
  if (planning.workbench_error) return <QueryError error={planning.workbench_error} />
  if (historyQuery.isError) return <QueryError error={historyQuery.error} onRetry={() => void historyQuery.refetch()} />
  if (healthQuery.isError) return <QueryError error={healthQuery.error} onRetry={() => void healthQuery.refetch()} />
  if (confirmationGateQuery.isError) return <QueryError error={confirmationGateQuery.error} onRetry={() => void confirmationGateQuery.refetch()} />
  if (profileQuery.isError) return <QueryError error={profileQuery.error} onRetry={() => void profileQuery.refetch()} />
  if (!planning.session_id || !historyQuery.data?.length || !current || !healthQuery.data || !confirmationGateQuery.data || !profileQuery.data) return <div className="empty-panel"><Empty description="后端没有返回 PlanVersion History" /></div>

  const confirmationGate = confirmationGateQuery.data

  const compare = () => {
    if (selected.length === 2) navigate(`/what-if-compare?left=${encodeURIComponent(selected[0])}&right=${encodeURIComponent(selected[1])}`)
  }

  const refreshConfirmationViews = async () => {
    await queryClient.fetchQuery({ queryKey: ['workbench-state'], queryFn: api.workbenchState, staleTime: 0 })
    await Promise.all([
      queryClient.refetchQueries({ queryKey: ['confirmation-gate'], type: 'all' }),
      queryClient.refetchQueries({ queryKey: ['monthly-filling'], type: 'all' }),
      queryClient.refetchQueries({ queryKey: ['plan-history'], type: 'all' }),
      queryClient.refetchQueries({ queryKey: ['plan-health'], type: 'all' }),
    ])
  }

  const confirmCurrentPlan = async () => {
    if (confirming || confirmationGate.can_confirm !== true || !planning.session_id || planning.planning_revision === null || !planning.current_plan_version_id) return
    setConfirming(true)
    try {
      const result = await api.confirmPlan(
        planning.session_id,
        planning.current_plan_version_id,
        planning.planning_revision,
      )
      if (!result.ok || result.outcome !== 'CONFIRMED' || !result.plan_version_id) {
        message.error(result.message || result.outcome)
        return
      }
      message.success(`后端已确认 PlanVersion：${shortId(result.plan_version_id)}`)
      try {
        await refreshConfirmationViews()
      } catch (refreshError) {
        message.error(`Confirm 已成功，但状态刷新失败：${refreshError instanceof Error ? refreshError.message : '请重新加载页面'}`)
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        try {
          await refreshConfirmationViews()
        } catch (refreshError) {
          message.error(`Confirm 被后端拒绝，且当前状态刷新失败：${refreshError instanceof Error ? refreshError.message : '请重新加载页面'}`)
          return
        }
        message.error(confirmConflictMessage(error))
        return
      }
      message.error(error instanceof Error ? error.message : 'Confirm 失败')
    } finally {
      setConfirming(false)
    }
  }
  const columns: ColumnsType<PlanHistory> = [
    { title: '版本', dataIndex: 'plan_version_id', render: (value: string) => <Typography.Text copyable={{ text: value }}>{shortId(value)}</Typography.Text> },
    { title: '状态', dataIndex: 'status', render: (value: string) => <StatusTag value={value} /> },
    { title: '父版本', dataIndex: 'parent_plan_version_id', render: (value: string | null) => shortId(value) },
    { title: '确认基准', dataIndex: 'base_confirmed_plan_version_id', render: (value: string | null) => shortId(value) },
    { title: '创建时间', dataIndex: 'created_at', render: (value: string) => formatDateTime(value) },
    { title: '确认时间', dataIndex: 'confirmed_at', render: (value: string | null) => formatDateTime(value) },
    { title: '销售输入', dataIndex: 'sales_plan_version_id', render: (value: string) => shortId(value) },
    { title: '审计事件', key: 'events', render: (_value, row) => `${row.actions.length + row.decision_events.length} 项` },
  ]

  return <div className="page-container plan-version-page">
    <PageHeader title="版本与确认" subtitle="先确认当前候选，再查看完整历史" actions={<Space><Button icon={<AuditOutlined />} disabled={selected.length !== 2} onClick={compare}>查看 VS 对比</Button></Space>} />
    <Row gutter={[14, 14]}>
      <Col xs={24} xxl={16}>
        <ConfirmationPanel
          current={current}
          gate={confirmationGate}
          plannerState={planning.workbenchState?.planner_state || null}
          confirming={confirming}
          onConfirm={() => void confirmCurrentPlan()}
        />
      </Col>
      <Col xs={24} xxl={8}>
        <Card size="small" title="当前会话路径">
          <SessionPath versions={historyQuery.data} />
        </Card>
      </Col>
    </Row>
    <Collapse
      style={{ marginTop: 14 }}
      items={[{
        key: 'history-and-path',
        label: '版本路径、完整历史与审计事件',
        children: (
          <>
            {choiceTreeQuery.data && (
              <ChoiceTreeSection
                tree={choiceTreeQuery.data}
                headId={planning.current_plan_version_id}
                selected={selected}
                onToggleSelect={(id) => setSelected((keys) => (keys.includes(id) ? keys.filter((key) => key !== id) : keys.length < 2 ? [...keys, id] : keys))}
                onCompare={compare}
                onViewFilling={(id) => navigate(`/v5/monthly-filling?plan_version_id=${encodeURIComponent(id)}`)}
                onViewDecision={(id) => setDecisionFocus(id)}
              />
            )}
            <Card title="完整版本历史" className="history-card"><Table<PlanHistory> rowKey="plan_version_id" size="small" bordered rowSelection={{ selectedRowKeys: selected, onChange: (keys) => setSelected(keys as string[]), getCheckboxProps: () => ({ disabled: false }) }} columns={columns} dataSource={historyQuery.data} pagination={{ pageSize: 10, showSizeChanger: false }} scroll={{ x: 980 }} /></Card>
            <Card id="decision-log" title="版本事件" className="decision-card"><div className="timeline-list">{decisionLogNode?.decision_events.length ? decisionLogNode.decision_events.map((event, index) => <div className="timeline-row" key={`${event.event_type}-${index}`}><span className="timeline-dot" /><div><strong>{event.display_name}</strong><span>{formatDateTime(event.occurred_at)}</span></div></div>) : <span className="muted">后端未返回版本事件</span>}</div></Card>
          </>
        ),
      }]}
    />
    <div className="bottom-note"><span><SafetyOutlined /> 确认结果、版本状态与修订号以后端返回为准。</span><span><LinkOutlined /> 历史版本与审计证据均保留。</span></div>
  </div>
}

function GateItem({ icon, title, value, status, note }: { icon: React.ReactNode; title: string; value: string; status?: string | null; note: string }) {
  return <div className="gate-item"><div className="gate-icon">{icon}</div><div><strong>{title}</strong><div className="gate-value">{value}</div><small>{note}</small></div>{status ? <StatusTag value={status} short /> : null}</div>
}

function SummaryItem({ icon, title, value, onClick }: { icon: React.ReactNode; title: string; value: string; onClick?: () => void }) {
  return <button className="summary-item" onClick={onClick} disabled={!onClick}><span className="summary-icon">{icon}</span><span><strong>{title}</strong><small>{value}</small></span><LinkOutlined /></button>
}

function WarningIcon() {
  return <span className="warning-icon">!</span>
}

function confirmConflictMessage(error: ApiError) {
  const detail = typeof error.detail === 'object' && error.detail !== null
    ? error.detail as Record<string, unknown>
    : {}
  const outcome = typeof detail.outcome === 'string' ? detail.outcome : null
  const serverMessage = typeof detail.message === 'string' ? detail.message : null
  if (outcome === 'STALE_BASE_VERSION') return serverMessage || 'planning revision 已变化，请以最新后端状态为准'
  return [outcome, serverMessage].filter(Boolean).join('：') || error.message || 'Confirm 被后端拒绝'
}

function eventEvidenceCount(item: PlanHistory) {
  return [...item.actions, ...item.decision_events].reduce((count, event) => count + event.evidence_refs.length, 0)
}

// ---------------------------------------------------------------------------
// Epic C: Choice Tree renderer. Renders the backend-owned tree shape
// (GET /sessions/{id}/choice-tree); the frontend never invents tree nodes.
// ---------------------------------------------------------------------------

const ROLE_COLOR: Record<string, string> = {
  RECOMMENDATION: 'blue',
  WHAT_IF: 'orange',
  ALTERNATIVE: 'purple',
}

function ChoiceTreeSection({
  tree,
  headId,
  selected,
  onToggleSelect,
  onCompare,
  onViewFilling,
  onViewDecision,
}: {
  tree: ChoiceTree
  headId: string | null
  selected: string[]
  onToggleSelect: (id: string) => void
  onCompare: () => void
  onViewFilling: (id: string) => void
  onViewDecision: (id: string) => void
}) {
  const byParent = new Map<string | null, ChoiceTreeNode[]>()
  for (const node of tree.nodes) {
    const key = node.parent_version_id
    const bucket = byParent.get(key) || []
    bucket.push(node)
    byParent.set(key, bucket)
  }
  const roots = byParent.get(null) || []
  const edges = tree.comparison_edges || []
  const edgeFor = (id: string) => edges.filter((edge) => edge.left === id || edge.right === id)

  const renderNode = (node: ChoiceTreeNode, depth: number) => {
    const nodeEdges = edgeFor(node.version_id)
    const isHead = node.version_id === headId
    return (
      <div key={node.version_id}>
        <div className="choice-tree-row" style={{ paddingLeft: depth * 28 }}>
          <span className="tree-connector">{depth > 0 ? '└─' : '●'}</span>
          <Tag>{node.display_sequence ? `V${node.display_sequence}` : shortId(node.version_id)}</Tag>
          <Tag color={ROLE_COLOR[node.role] || 'default'}>{node.role}</Tag>
          <StatusTag value={node.status} />
          {node.confirmed ? <Tag color="green">已选中最终节点</Tag> : !isHead ? <Tag>未选中分支</Tag> : <Tag color="blue">当前 head</Tag>}
          <Space size={4}>
            <Button size="small" icon={<FileSearchOutlined />} onClick={() => onViewFilling(node.version_id)}>查看 Filling</Button>
            <Button size="small" icon={<AuditOutlined />} onClick={() => onViewDecision(node.version_id)}>查看决策</Button>
            <Button size="small" type={selected.includes(node.version_id) ? 'primary' : 'default'} onClick={() => onToggleSelect(node.version_id)}>
              {selected.includes(node.version_id) ? '已选对比' : '选为对比'}
            </Button>
          </Space>
          <Typography.Text className="muted" style={{ marginLeft: 8 }}>{shortId(node.version_id)}</Typography.Text>
        </div>
        {nodeEdges.length > 0 && (
          <div className="choice-tree-edges" style={{ paddingLeft: depth * 28 + 26 }}>
            {nodeEdges.map((edge) => (
              <div key={edge.comparison_id} className="muted">
                ⚖ 对比 {shortId(edge.left)} → {shortId(edge.right)}
                {edge.selected ? <Tag color="green">已选 {shortId(edge.selected)}</Tag> : null}
                {edge.outcome ? <Tag>{edge.outcome}</Tag> : null}
                {edge.summary ? <span> · {edge.summary}</span> : null}
              </div>
            ))}
          </div>
        )}
        {(byParent.get(node.version_id) || []).map((child) => renderNode(child, depth + 1))}
      </div>
    )
  }

  return (
    <Card
      size="small"
      title={<Space><ApartmentOutlined />版本选择路径 <small className="muted">展示当前会话的候选与分支</small></Space>}
      extra={<Button size="small" disabled={selected.length !== 2} onClick={onCompare}>对比已选（{selected.length}/2）</Button>}
      style={{ marginBottom: 14 }}
    >
      {tree.nodes.length === 0 ? (
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="后端未返回版本节点" />
      ) : (
        <div className="choice-tree">{roots.map((node) => renderNode(node, 0))}</div>
      )}
    </Card>
  )
}
