import { useState } from 'react'
import { Card, Col, Row, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { usePlanning } from '../../app/PlanningContext'
import type { PlanningIssue, ActionView } from '../../types/api'
import { IssueQueue } from './IssueQueue'
import { IssueDecisionPanel } from './IssueDecisionPanel'

export function Issues() {
  const planning = usePlanning()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [selectedIssue, setSelectedIssue] = useState<PlanningIssue | null>(null)
  const [previewResult, setPreviewResult] = useState<any | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [applying, setApplying] = useState(false)

  const issuesQuery = useQuery({
    queryKey: ['issues', planning.current_plan_version_id],
    queryFn: () => api.getIssues(planning.current_plan_version_id as string),
    enabled: Boolean(planning.current_plan_version_id),
    staleTime: 30_000,
  })
  const factoryQuery = useQuery({
    queryKey: ['factory-model-versions'],
    queryFn: () => api.factoryModelVersions(),
  })
  const activeFactory = (factoryQuery.data || []).find((v: any) => v.status === 'ACTIVE')
  const factoryDetailQuery = useQuery({
    queryKey: ['factory-model-version-detail', activeFactory?.factory_model_version_id],
    queryFn: () => api.factoryModelVersionDetail(activeFactory!.factory_model_version_id),
    enabled: Boolean(activeFactory),
  })
  const workshopForTypeclass: Record<string, string> = {}
  for (const tc of factoryDetailQuery.data?.factory_model?.typeclasses || []) {
    workshopForTypeclass[String(tc.typeclass_id)] = String(tc.workshop_id)
  }

  const previewMutation = useMutation({
    mutationFn: ({ actionType, payload }: { actionType: string; payload: Record<string, unknown> }) =>
      api.previewAction(planning.session_id!, planning.planning_revision!, actionType, payload),
    onSuccess: (data) => {
      setPreviewResult(data)
      setPreviewing(false)
    },
    onError: (error: any) => {
      message.error(error?.message || 'Preview 执行失败')
      setPreviewing(false)
    },
  })

  const applyMutation = useMutation({
    mutationFn: ({ actionType, payload }: { actionType: string; payload: Record<string, unknown> }) =>
      api.applyAction(planning.session_id!, planning.planning_revision!, actionType, payload),
    onSuccess: (data) => {
      if (data.outcome === 'PLAN_CREATED' && data.plan_version_id) {
        planning.adoptBackendHead(data.plan_version_id, data.planning_revision ?? 0)
        queryClient.invalidateQueries()
        message.success('已应用并重新排产')
        setPreviewResult(null)
        setSelectedIssue(null)
      } else {
        message.warning(data.message || data.outcome)
      }
      setApplying(false)
    },
    onError: (error: any) => {
      if (error?.status === 409) {
        queryClient.invalidateQueries({ queryKey: ['workbench-state'] })
        message.error('计划已变化，请刷新后重新操作')
      } else {
        message.error(error?.message || 'Apply 执行失败')
      }
      setApplying(false)
    },
  })

  const handlePreview = (action: ActionView) => {
    if (!planning.session_id || planning.planning_revision === null) return
    setPreviewing(true)
    setPreviewResult(null)
    const schema = action.parameters_schema as any
    const defaults: Record<string, unknown> = {}
    for (const key of schema?.required || []) {
      if (schema.properties?.[key]?.default !== undefined) {
        defaults[key] = schema.properties[key].default
      }
    }
    const payload =
      action.action_type === 'ENABLE_WORKING_MODE'
        ? { ...defaults, working_mode_id: 'DOUBLE_SHIFT' }
        : defaults
    previewMutation.mutate({ actionType: action.action_type, payload })
  }

  const handleApply = (action: ActionView) => {
    if (!planning.session_id || planning.planning_revision === null || !previewResult) {
      message.info('先预览动作，再应用')
      return
    }
    setApplying(true)
    const payload =
      action.action_type === 'ENABLE_WORKING_MODE'
        ? { working_mode_id: 'DOUBLE_SHIFT' }
        : {}
    applyMutation.mutate({ actionType: action.action_type, payload })
  }

  if (planning.workbench_loading) return <PageState kind="loading" rows={6} />
  if (planning.workbench_error)
    return <PageState kind="system-error" error={planning.workbench_error} onRetry={() => window.location.reload()} />
  if (!planning.current_plan_version_id)
    return <PageState kind="empty" title="当前工作台没有 PlanVersion" />
  if (issuesQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (issuesQuery.error)
    return <PageState kind="system-error" error={issuesQuery.error} onRetry={() => window.location.reload()} />

  const issues = issuesQuery.data || []

  return (
    <div className="page-container" data-testid="issues-ready">
      <PageHeader title="待处理问题" subtitle="Human LOOP：先看发生了什么，再决定动作" />
      {issues.length === 0 ? (
        <PageState kind="empty" title="当前计划没有待处理问题" />
      ) : (
        <Row gutter={[14, 14]}>
          <Col xs={24} lg={9}>
            <Card size="small" title={`问题队列（${issues.length}）`}>
              <IssueQueue
                issues={issues}
                selectedId={selectedIssue?.issue_id ?? null}
                workshopForTypeclass={workshopForTypeclass}
                onSelect={(issue) => {
                  setSelectedIssue(issue)
                  setPreviewResult(null)
                }}
              />
            </Card>
          </Col>
          <Col xs={24} lg={15}>
            <Card size="small" title="决策详情">
              <IssueDecisionPanel
                issue={selectedIssue}
                previewing={previewing}
                applying={applying}
                onPreviewAction={handlePreview}
                onApplyAction={handleApply}
                onCompare={() => {
                  if (previewResult?.what_if_plan_version_id) {
                    navigate(
                      `/what-if-compare?left=${encodeURIComponent(planning.current_plan_version_id || '')}&right=${encodeURIComponent(previewResult.what_if_plan_version_id)}`,
                    )
                  }
                }}
                previewResult={previewResult}
              />
            </Card>
          </Col>
        </Row>
      )}
    </div>
  )
}
