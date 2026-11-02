import { useMemo } from 'react'
import { Alert, Button, Card, Space, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { PageSkeleton, PageState } from '../../components/PageState'
import type {
  CalendarVersion,
  FactoryModelVersion,
  InitialStateSnapshot,
  PreflightResult,
  StartSessionRequest,
  WipTargetVersion,
} from '../../types/api'
import type { StartPlanningDraft } from './types'

const FACTORY_QUERY_KEY = ['factory-model-versions'] as const
const CALENDAR_QUERY_KEY = ['calendar-versions'] as const
const WIP_QUERY_KEY = ['wip-target-versions'] as const
const INITIAL_QUERY_KEY = ['initial-state-snapshots'] as const
const INPUT_AUTHORITY_QUERY_KEYS = [
  FACTORY_QUERY_KEY,
  CALENDAR_QUERY_KEY,
  WIP_QUERY_KEY,
  INITIAL_QUERY_KEY,
] as const

interface PreflightEnvelope {
  inputsIdentity: string
  result: PreflightResult
}

function serializeInputs(inputs: StartSessionRequest): string {
  const canonicalize = (value: unknown): unknown => {
    if (Array.isArray(value)) return value.map(canonicalize)
    if (value && typeof value === 'object') {
      return Object.fromEntries(
        Object.entries(value as Record<string, unknown>)
          .sort(([left], [right]) => left.localeCompare(right))
          .map(([key, item]) => [key, canonicalize(item)]),
      )
    }
    return value
  }
  return JSON.stringify(canonicalize(inputs))
}

function activeVersion<T extends { status: string }>(versions: T[] | undefined): T | undefined {
  return versions?.find((version) => version.status === 'ACTIVE')
}

function SystemErrorState({
  error,
  retryLabel,
  onRetry,
}: {
  error: unknown
  retryLabel: string
  onRetry: () => void
}) {
  return (
    <Alert
      type="error"
      showIcon
      message="系统请求失败"
      description={error instanceof Error ? error.message : '未知错误'}
      action={
        <Button aria-label={retryLabel} onClick={onRetry}>
          重试
        </Button>
      }
    />
  )
}

const CHECK_LABELS: Record<string, string> = {
  sales_full_year: '12 个月销售与日历覆盖（sales_full_year）',
  calendar_full_year: '12 个月销售与日历覆盖（calendar_full_year）',
  wip_targets_complete: 'WIP 目标水位完整性',
  wip_targets_within_physical_max: 'WIP 目标不超过物理上限',
  factory_required_nodes: '工厂必需节点',
  factory_required_modes: '工厂必需工作模式',
  initial_state_valid: '初始状态有效性',
  base_confirmed_valid: '确认基准版本有效性',
  context_constructible: '排产上下文可构建',
}

export function PreflightGenerateStep({
  draft,
  onBack,
  onComplete,
}: {
  draft: StartPlanningDraft
  onBack: () => void
  onComplete: (result: {
    planVersionId: string | null
    issueCount: number
  }) => void
}) {
  const queryClient = useQueryClient()
  const factory = useQuery({ queryKey: FACTORY_QUERY_KEY, queryFn: () => api.factoryModelVersions(), retry: false })
  const calendar = useQuery({ queryKey: CALENDAR_QUERY_KEY, queryFn: () => api.calendarVersions(), retry: false })
  const wip = useQuery({ queryKey: WIP_QUERY_KEY, queryFn: () => api.wipTargetVersions(), retry: false })
  const initial = useQuery({ queryKey: INITIAL_QUERY_KEY, queryFn: () => api.initialStateSnapshots(), retry: false })
  const authorityQueries = [factory, calendar, wip, initial]
  const authorityFetching = authorityQueries.some((query) => query.isFetching)
  const failedAuthorityQuery = authorityQueries.find(
    (query) => query.isError || query.isRefetchError,
  )
  const authorityError = Boolean(failedAuthorityQuery)
  const authorityHasData = authorityQueries.every((query) => query.data !== undefined)
  const authoritySettled = !authorityFetching && !authorityError && authorityHasData

  const candidateInputs = useMemo<StartSessionRequest | null>(() => {
    const activeFactory = activeVersion(factory.data)
    const activeCalendar = activeVersion(calendar.data)
    const activeWip = activeVersion(wip.data)
    const activeInitial = activeVersion(initial.data)
    if (!draft.salesPlanVersionId || !activeFactory || !activeCalendar || !activeWip || !activeInitial) {
      return null
    }
    return {
      sales_plan_version_id: draft.salesPlanVersionId,
      factory_model_version_id: activeFactory.factory_model_version_id,
      calendar_version_id: activeCalendar.calendar_version_id,
      initial_state_snapshot_id: activeInitial.initial_state_snapshot_id,
      wip_target_version_id: activeWip.wip_target_version_id,
      planning_year: draft.planningYear,
      base_confirmed_plan_version_id: draft.baseConfirmedPlanVersionId ?? undefined,
      work_note: draft.workNote || undefined,
      planning_conditions: draft.conditionChanges.flatMap((item) => item.planningConditions),
    }
  }, [draft, factory.data, calendar.data, wip.data, initial.data])
  const inputsIdentity = candidateInputs ? serializeInputs(candidateInputs) : null
  const preflightQueryKey = ['start-planning-preflight', inputsIdentity] as const
  const preflight = useQuery<PreflightEnvelope>({
    queryKey: preflightQueryKey,
    queryFn: async () => {
      if (!candidateInputs || !inputsIdentity) throw new Error('当前排产输入不完整')
      return {
        inputsIdentity,
        result: await api.preflight(candidateInputs),
      }
    },
    enabled: Boolean(candidateInputs && inputsIdentity && authoritySettled),
    retry: false,
  })
  const preflightError = preflight.isError || preflight.isRefetchError
  const currentPreflight = preflight.data?.inputsIdentity === inputsIdentity
    ? preflight.data.result
    : null
  const authorized = Boolean(
    candidateInputs
    && inputsIdentity
    && authoritySettled
    && preflight.data?.inputsIdentity === inputsIdentity
    && !preflight.isFetching
    && !preflightError
    && currentPreflight?.outcome === 'PASS',
  )

  const startAndGenerate = useMutation({
    mutationFn: async () => {
      const queryState = queryClient.getQueryState(preflightQueryKey)
      const queryData = queryClient.getQueryData<PreflightEnvelope>(preflightQueryKey)
      const authorityStillSettled = INPUT_AUTHORITY_QUERY_KEYS.every((queryKey) => {
        const state = queryClient.getQueryState(queryKey)
        return state?.status === 'success'
          && state.fetchStatus === 'idle'
          && state.data !== undefined
      })
      const currentFactory = activeVersion(
        queryClient.getQueryData<FactoryModelVersion[]>(FACTORY_QUERY_KEY),
      )
      const currentCalendar = activeVersion(
        queryClient.getQueryData<CalendarVersion[]>(CALENDAR_QUERY_KEY),
      )
      const currentWip = activeVersion(
        queryClient.getQueryData<WipTargetVersion[]>(WIP_QUERY_KEY),
      )
      const currentInitial = activeVersion(
        queryClient.getQueryData<InitialStateSnapshot[]>(INITIAL_QUERY_KEY),
      )
      const authorityInputsStillCurrent = Boolean(
        candidateInputs
        && currentFactory?.factory_model_version_id === candidateInputs.factory_model_version_id
        && currentCalendar?.calendar_version_id === candidateInputs.calendar_version_id
        && currentWip?.wip_target_version_id === candidateInputs.wip_target_version_id
        && currentInitial?.initial_state_snapshot_id === candidateInputs.initial_state_snapshot_id,
      )
      if (
        !candidateInputs
        || !inputsIdentity
        || serializeInputs(candidateInputs) !== inputsIdentity
        || !authorityStillSettled
        || !authorityInputsStillCurrent
        || queryState?.status !== 'success'
        || queryState.fetchStatus !== 'idle'
        || queryData?.inputsIdentity !== inputsIdentity
        || queryData.result.outcome !== 'PASS'
      ) {
        throw new Error('当前输入尚未通过 Preflight，请重新检查')
      }
      const started = await api.startSession(candidateInputs)
      if (started.outcome !== 'SESSION_STARTED' || !started.session_id) {
        throw new Error(`启动会话失败: ${started.outcome}`)
      }
      return api.generatePlan(started.session_id, {
        expected_planning_revision: started.planning_revision ?? 0,
      })
    },
    onSuccess: (result) => {
      if (result.outcome === 'PLAN_CREATED' && result.plan_version_id) {
        const issues = Array.isArray(result.issues) ? result.issues : []
        queryClient.invalidateQueries({ queryKey: ['workbench-state'] })
        onComplete({ planVersionId: result.plan_version_id, issueCount: issues.length })
      } else {
        message.error(`生成计划失败: ${result.outcome}`)
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '生成计划失败'),
  })

  const failedChecks = (currentPreflight?.checks || []).filter((c) => !c.ok)

  const retryAuthority = () => {
    void Promise.all(authorityQueries.map((query) => query.refetch()))
  }

  return (
    <Card size="small" title="第 3 步 · 检查生成">
      {authorityError ? (
        <SystemErrorState
          error={failedAuthorityQuery?.error || new Error('输入版本查询失败')}
          retryLabel="重试输入查询"
          onRetry={retryAuthority}
        />
      ) : authorityFetching || !authorityHasData ? (
        <PageSkeleton rows={4} />
      ) : !candidateInputs || !inputsIdentity ? (
        <PageState
          kind="business-blocked"
          title="输入尚未就绪"
          reasons={['销售计划或基础设置缺少当前生效版本']}
        />
      ) : preflightError ? (
        <SystemErrorState
          error={preflight.error || new Error('Preflight 请求失败')}
          retryLabel="重试 Preflight"
          onRetry={() => void preflight.refetch()}
        />
      ) : preflight.isFetching || !currentPreflight ? (
        <PageSkeleton rows={4} />
      ) : authorized ? (
        <div>
          <div style={{ marginBottom: 12 }}>
            <strong style={{ color: 'var(--colorSuccess, #1a8f5c)' }}>✓ 输入检查通过</strong>
            <span className="muted" style={{ marginLeft: 8 }}>
              完整 12 个月销售与日历、WIP 目标、工厂节点均就绪
            </span>
          </div>
          <Space>
            <Button onClick={onBack}>上一步：排产条件</Button>
            <Button
              type="primary"
              loading={startAndGenerate.isPending}
              disabled={!authorized}
              onClick={() => startAndGenerate.mutate()}
            >
              生成年度计划
            </Button>
          </Space>
        </div>
      ) : (
        <div>
          <PageState
            kind="business-blocked"
            title="输入尚未就绪"
            reasons={failedChecks.map(
              (c) => `${CHECK_LABELS[c.check] || c.check} 未通过：${c.detail}`,
            )}
            action={
              failedChecks.some((c) => c.check.includes('sales') || c.check.includes('calendar')) ? (
                <Button onClick={() => (window.location.href = '/sales')}>修复销售计划</Button>
              ) : undefined
            }
          />
          <Space style={{ marginTop: 12 }}>
            <Button onClick={onBack}>上一步：排产条件</Button>
            <Button type="primary" disabled>
              生成年度计划
            </Button>
          </Space>
        </div>
      )}
    </Card>
  )
}
