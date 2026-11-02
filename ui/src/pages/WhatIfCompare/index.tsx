import { ArrowLeftOutlined, SwapOutlined } from '@ant-design/icons'
import { Button, Card, Empty, Space, Tag, Typography, message } from 'antd'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useState } from 'react'
import { ApiError } from '../../api/client'
import { api } from '../../api/planning'
import { QueryError, QueryLoading } from '../../components/ApiState'
import { PageHeader } from '../../components/PageHeader'
import { usePlanning } from '../../app/PlanningContext'
import { shortId } from '../../utils/format'
import { CoreMetricTable } from './CoreMetricTable'
import { CompareEvidenceTabs } from './CompareEvidenceTabs'
import { ProductionOverviewMatrix } from './ProductionOverviewMatrix'

// Epic B freeze: three evidence sections only (Decision / Derived Impact /
// Intent). Every cell is a backend fact; V5 verdict block comes first.

export function WhatIfCompare() {
  const planning = usePlanning()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const [applying, setApplying] = useState(false)
  const left = params.get('left')
  const right = params.get('right')
  const query = useQuery({ queryKey: ['plan-compare', left, right], queryFn: () => api.comparePlans(left as string, right as string), enabled: Boolean(left && right) })
  const leftAnnualQuery = useQuery({ queryKey: ['annual-calendar', left, 'compare-left'], queryFn: () => api.annualCalendar(left as string), enabled: Boolean(left), retry: false })
  const rightAnnualQuery = useQuery({ queryKey: ['annual-calendar', right, 'compare-right'], queryFn: () => api.annualCalendar(right as string), enabled: Boolean(right), retry: false })
  const preview = planning.manual_filling_preview
  const draftScope = planning.manual_filling_draft_scope
  const canApply = Boolean(
    query.data
    && left
    && right
    && planning.session_id
    && planning.planning_revision !== null
    && planning.manual_filling_draft.length > 0
    && preview
    && preview.base_plan_version_id === left
    && preview.what_if_plan_version_id === right
    && preview.planning_revision === planning.planning_revision
    && planning.current_plan_version_id === preview.base_plan_version_id
    && draftScope?.plan_version_id === preview.base_plan_version_id
    && draftScope.month === preview.month,
  )

  const applyDraft = async () => {
    if (!canApply || !planning.session_id || planning.planning_revision === null) return
    setApplying(true)
    try {
      const result = await api.applyAction(
        planning.session_id,
        planning.planning_revision,
        'MANUAL_FILLING_BATCH',
        { items: planning.manual_filling_draft },
      )
      if (!result.ok || !result.plan_version_id || typeof result.planning_revision !== 'number') {
        message.error(result.message || result.outcome)
        return
      }
      planning.adoptBackendHead(result.plan_version_id, result.planning_revision)
      planning.clearManualFillingDraft()
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['workbench-state'] }),
        queryClient.invalidateQueries({ queryKey: ['annual-calendar'] }),
        queryClient.invalidateQueries({ queryKey: ['monthly-filling'] }),
        queryClient.invalidateQueries({ queryKey: ['plan-history'] }),
        queryClient.invalidateQueries({ queryKey: ['plan-health'] }),
        queryClient.invalidateQueries({ queryKey: ['confirmation-gate'] }),
      ])
      message.success(`后端已生成新 PlanVersion：${shortId(result.plan_version_id)}`)
      navigate('/plan-version')
    } catch (error) {
      if (error instanceof ApiError && error.status === 409) {
        planning.clearManualFillingDraft()
        await queryClient.invalidateQueries({ queryKey: ['workbench-state'] })
        message.error('计划已变化，请刷新后重新编辑')
        return
      }
      message.error(error instanceof Error ? error.message : 'Apply 失败')
    } finally {
      setApplying(false)
    }
  }

  if (!left || !right) return <div className="page-container"><PageHeader title="版本比对" /><div className="empty-panel"><Empty description="请从版本历史选择两个版本进行比对" /></div></div>
  if (query.isLoading) return <QueryLoading />
  if (query.isError) return <QueryError error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return <div className="empty-panel"><Empty description="对比接口未返回数据" /></div>
  const comparison = query.data

  return <div className="page-container compare-page">
    <PageHeader title="版本比对" subtitle="12 个月生产总览 · 左右版本、差额与累计差额" actions={<Button icon={<ArrowLeftOutlined />} onClick={() => window.history.back()}>返回版本历史</Button>} />
    <Card className="problem-summary" title="对比版本">
      <div className="summary-strip">
        <span><Tag color="blue">当前计划（左）</Tag>{shortId(comparison.left_plan_version_id)}</span>
        <SwapOutlined style={{ fontSize: 16 }} />
        <span><Tag color="green">候选方案（右）</Tag>{shortId(comparison.right_plan_version_id)}</span>
        {comparison.summary && <Typography.Text className="muted"> · {comparison.summary}</Typography.Text>}
      </div>
    </Card>

    <div className="compare-verdict" data-testid="compare-verdict">
      <Card size="small" title="后端结论摘要">
        <div className="compare-verdict-summary">{comparison.verdict_summary || '后端未返回结论摘要'}</div>
        <Space wrap style={{ marginTop: 8 }}>
          {(comparison.advantages || []).map((metric) => (
            <Tag key={`adv-${metric.metric_id}`} color="green">优势：{metric.label}</Tag>
          ))}
          {(comparison.disadvantages || []).map((metric) => (
            <Tag key={`dis-${metric.metric_id}`} color="red">代价：{metric.label}</Tag>
          ))}
          {(comparison.key_differences || []).length > 0 && (
            <Tag color="blue">关键差异 {comparison.key_differences.length} 项</Tag>
          )}
        </Space>
      </Card>
    </div>

    <ProductionOverviewMatrix
      leftId={comparison.left_plan_version_id}
      rightId={comparison.right_plan_version_id}
      leftAnnual={leftAnnualQuery.data}
      rightAnnual={rightAnnualQuery.data}
      loading={leftAnnualQuery.isLoading || rightAnnualQuery.isLoading}
    />

    <Card size="small" title="年度核心指标（后端判定）" style={{ marginTop: 14 }}>
      <CoreMetricTable metrics={comparison.core_metrics || []} />
    </Card>

    <Card size="small" title="证据明细" style={{ marginTop: 14 }}>
      <CompareEvidenceTabs
        keyDifferences={comparison.key_differences || []}
        decisionDiff={[...comparison.summary_diff, ...comparison.changed_blocks]}
        derivedDiff={[
          ...comparison.metric_diff,
          ...comparison.changed_days.filter((entry) => entry.category === 'DERIVED' || entry.category === 'ORGANIZATIONAL_DELTA'),
        ]}
        intentDiff={comparison.intent_diff || []}
      />
    </Card>

    <div className="bottom-actions">
      <Button onClick={() => navigate('/v5/monthly-filling')}>返回 Filling</Button>
      <Button type="primary" loading={applying} disabled={!canApply} onClick={() => void applyDraft()}>应用 Draft 并重新排产</Button>
    </div>
    <span className="muted compare-context">当前版本：{shortId(planning.current_plan_version_id)} · 只展示确定性后端事实，不做推测性评分</span>
  </div>
}
