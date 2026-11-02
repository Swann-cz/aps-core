import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Alert, Steps } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { usePlanning } from '../../app/PlanningContext'
import { ChangeSourceStep } from './ChangeSourceStep'
import { UpdateInputsStep } from './UpdateInputsStep'
import { ImpactScopeStep } from './ImpactScopeStep'
import { GenerateCompareStep } from './GenerateCompareStep'
import { validatedBaseDays } from './preflightAuthority'
import type { StartSessionRequest } from '../../types/api'
import {
  EMPTY_COMMAND_PROGRESS,
  startUncertainMarkerKey,
  type ChangeSource,
  type NewRoundTask,
  type PreflightEnvelope,
} from './types'

const TASK_ORDER: NewRoundTask[] = ['source', 'inputs', 'scope', 'generate-compare']
const TASK_TITLES: Record<NewRoundTask, string> = {
  source: '变化来源',
  inputs: '更新输入',
  scope: '影响范围',
  'generate-compare': '生成与比对',
}

const CHANGE_SOURCES: ChangeSource[] = ['actual', 'sales', 'conditions', 'combined']

function isChangeSource(value: string | null): value is ChangeSource {
  return CHANGE_SOURCES.includes(value as ChangeSource)
}

export function RollingReplan() {
  const planning = usePlanning()
  const navigate = useNavigate()
  const [params] = useSearchParams()
  const [task, setTask] = useState<NewRoundTask>('source')
  const [source, setSource] = useState<ChangeSource>(() => {
    const requested = params.get('source')
    return isChangeSource(requested) ? requested : 'actual'
  })
  const [actualRevisionId, setActualRevisionId] = useState<string | null>(() => params.get('revision_id'))
  const [salesPlanVersionId, setSalesPlanVersionId] = useState<string | null>(null)
  const [authorityRefreshing, setAuthorityRefreshing] = useState(false)
  const [baseProjectionInvalid, setBaseProjectionInvalid] = useState(false)
  const [commandProgress, setCommandProgress] = useState(EMPTY_COMMAND_PROGRESS)
  const previousIntentIdentity = useRef<string | null>(null)
  const baseConfirmedId =
    params.get('base')
    || planning.workbench?.base_confirmed_plan_version_id
    || (planning.workbench?.version_status === 'CONFIRMED' ? planning.current_plan_version_id : null)

  const sales = useQuery({ queryKey: ['sales-plan-versions'], queryFn: () => api.salesPlanVersions(), retry: false })
  const factory = useQuery({ queryKey: ['factory-model-versions'], queryFn: () => api.factoryModelVersions(), retry: false })
  const calendar = useQuery({ queryKey: ['calendar-versions'], queryFn: () => api.calendarVersions(), retry: false })
  const wip = useQuery({ queryKey: ['wip-target-versions'], queryFn: () => api.wipTargetVersions(), retry: false })
  const initial = useQuery({ queryKey: ['initial-state-snapshots'], queryFn: () => api.initialStateSnapshots(), retry: false })
  const versionQueries = [sales, factory, calendar, wip, initial]
  const versionsFetching = versionQueries.some((query) => query.isFetching)
  const versionsError = versionQueries.some((query) => query.isError || query.isRefetchError)
  const versionsHaveData = versionQueries.every((query) => query.data !== undefined)
  const workbenchError = Boolean(planning.workbench_error)
  const inputAuthorityFetching = authorityRefreshing || versionsFetching || planning.workbench_fetching
  const inputAuthorityError = versionsError || workbenchError
  const inputsSettled = !inputAuthorityFetching
    && !inputAuthorityError
    && versionsHaveData
    && planning.workbench !== undefined
  const activeSales = (sales.data || []).find((item) => item.status === 'ACTIVE')
  const activeFactory = (factory.data || []).find((item) => item.status === 'ACTIVE')
  const activeCalendar = (calendar.data || []).find((item) => item.status === 'ACTIVE')
  const activeWip = (wip.data || []).find((item) => item.status === 'ACTIVE')
  const activeInitial = (initial.data || []).find((item) => item.status === 'ACTIVE')
  const planningYear = planning.workbench?.planning_year ?? null
  const needsActual = source === 'actual' || source === 'combined'
  const intentIdentity = useMemo(() => JSON.stringify({
    source,
    baseConfirmedPlanVersionId: baseConfirmedId,
    actualRevisionId: needsActual ? actualRevisionId : null,
    salesPlanVersionId: source === 'sales' ? salesPlanVersionId : null,
  }), [actualRevisionId, baseConfirmedId, needsActual, salesPlanVersionId, source])

  useEffect(() => {
    if (activeSales) setSalesPlanVersionId(activeSales.sales_plan_version_id)
  }, [activeSales?.sales_plan_version_id])

  const inputGaps = [
    !baseConfirmedId && 'Confirmed Base',
    planningYear === null && 'planning_year',
    !activeSales && 'ACTIVE Sales',
    !activeFactory && 'ACTIVE Factory',
    !activeCalendar && 'ACTIVE Calendar',
    !activeWip && 'ACTIVE WIP Target',
    !activeInitial && 'ACTIVE Initial State',
  ].filter((item): item is string => Boolean(item))

  const candidateInputs = useMemo<StartSessionRequest | null>(() => {
    if (
      inputGaps.length > 0
      || !salesPlanVersionId
      || !activeFactory
      || !activeCalendar
      || !activeWip
      || !activeInitial
      || planningYear === null
      || !baseConfirmedId
      || (needsActual && !actualRevisionId)
    ) return null
    return {
      sales_plan_version_id: salesPlanVersionId,
      factory_model_version_id: activeFactory.factory_model_version_id,
      calendar_version_id: activeCalendar.calendar_version_id,
      ...(needsActual ? { actual_revision_id: actualRevisionId } : {}),
      initial_state_snapshot_id: activeInitial.initial_state_snapshot_id,
      wip_target_version_id: activeWip.wip_target_version_id,
      planning_year: planningYear,
      base_confirmed_plan_version_id: baseConfirmedId,
      work_note: `新一轮（${source}）`,
    }
  }, [
    activeCalendar,
    activeFactory,
    activeInitial,
    activeWip,
    actualRevisionId,
    baseConfirmedId,
    inputGaps.length,
    needsActual,
    planningYear,
    salesPlanVersionId,
    source,
  ])
  const inputs = inputsSettled ? candidateInputs : null
  const inputsIdentity = candidateInputs
    ? JSON.stringify(candidateInputs, Object.keys(candidateInputs).sort())
    : null

  useEffect(() => {
    const intentChanged = previousIntentIdentity.current !== intentIdentity
    previousIntentIdentity.current = intentIdentity
    let hasStartUncertainty = false
    try {
      hasStartUncertainty = window.sessionStorage.getItem(startUncertainMarkerKey(intentIdentity)) === '1'
    } catch {
      hasStartUncertainty = false
    }
    setCommandProgress((current) => {
      if (hasStartUncertainty) {
        return {
          inputsIdentity: inputsIdentity || null,
          baseConfirmedPlanVersionId: candidateInputs?.base_confirmed_plan_version_id || null,
          sessionId: null,
          planningRevision: null,
          generatedPlanId: null,
          status: 'BLOCKED',
          message: '该输入曾出现 Start 响应不确定，禁止再次 Start',
        }
      }
      return intentChanged ? EMPTY_COMMAND_PROGRESS : current
    })
    if (intentChanged) setBaseProjectionInvalid(false)
  }, [candidateInputs?.base_confirmed_plan_version_id, inputsIdentity, intentIdentity])
  const commandBlocked = commandProgress.status === 'BLOCKED'
  const preflight = useQuery<PreflightEnvelope>({
    queryKey: ['new-round-preflight', inputsIdentity],
    queryFn: async () => {
      if (!candidateInputs || !inputsIdentity) throw new Error('missing current inputs identity')
      return {
        inputsIdentity,
        result: await api.preflight(candidateInputs),
      }
    },
    enabled: Boolean(candidateInputs && (task === 'scope' || task === 'generate-compare')),
    retry: false,
  })
  const baseProjection = useQuery({
    queryKey: ['new-round-base-projection', baseConfirmedId],
    queryFn: () => api.annualCalendar(baseConfirmedId as string),
    enabled: Boolean(baseConfirmedId && !needsActual && (task === 'scope' || task === 'generate-compare')),
    retry: false,
  })

  const refreshInputAuthority = useCallback(async () => {
    if (!candidateInputs || !inputsIdentity) return false
    setAuthorityRefreshing(true)
    try {
      const [salesResult, factoryResult, calendarResult, wipResult, initialResult, workbenchResult] = await Promise.all([
        sales.refetch(),
        factory.refetch(),
        calendar.refetch(),
        wip.refetch(),
        initial.refetch(),
        planning.refetchWorkbench(),
      ])
      if (![salesResult, factoryResult, calendarResult, wipResult, initialResult, workbenchResult].every((result) => result.isSuccess && result.data !== undefined)) {
        return false
      }
      const currentSales = salesResult.data?.find((item) => item.status === 'ACTIVE')
      const currentFactory = factoryResult.data?.find((item) => item.status === 'ACTIVE')
      const currentCalendar = calendarResult.data?.find((item) => item.status === 'ACTIVE')
      const currentWip = wipResult.data?.find((item) => item.status === 'ACTIVE')
      const currentInitial = initialResult.data?.find((item) => item.status === 'ACTIVE')
      return currentSales?.sales_plan_version_id === candidateInputs.sales_plan_version_id
        && currentFactory?.factory_model_version_id === candidateInputs.factory_model_version_id
        && currentCalendar?.calendar_version_id === candidateInputs.calendar_version_id
        && currentWip?.wip_target_version_id === candidateInputs.wip_target_version_id
        && currentInitial?.initial_state_snapshot_id === candidateInputs.initial_state_snapshot_id
        && workbenchResult.data?.planning_year === candidateInputs.planning_year
    } finally {
      setAuthorityRefreshing(false)
    }
  }, [calendar, candidateInputs, factory, initial, inputsIdentity, planning, sales, wip])

  const retryInputAuthority = useCallback(() => {
    void Promise.all([
      sales.refetch(),
      factory.refetch(),
      calendar.refetch(),
      wip.refetch(),
      initial.refetch(),
      planning.refetchWorkbench(),
    ])
  }, [calendar, factory, initial, planning, sales, wip])

  const enterScope = useCallback(async () => {
    if (!await refreshInputAuthority()) return
    setTask('scope')
  }, [refreshInputAuthority])

  const enterGenerate = useCallback(async () => {
    if (!await refreshInputAuthority()) return
    const [, baseResult] = await Promise.all([
      preflight.refetch(),
      !needsActual ? baseProjection.refetch() : Promise.resolve(null),
    ])
    const invalidBase = (
      !needsActual
      && (
        !baseResult
        || !baseResult.isSuccess
        || validatedBaseDays(baseResult.data, baseConfirmedId, planningYear) === null
      )
    )
    setBaseProjectionInvalid(invalidBase)
    if (invalidBase) return
    setTask('generate-compare')
  }, [baseConfirmedId, baseProjection, needsActual, planningYear, preflight, refreshInputAuthority])

  return (
    <div className="page-container">
      <PageHeader title="发起新一轮" subtitle="所有变化来源统一走同一向导；基于 Confirmed Base 创建新 Session" />
      {commandBlocked && commandProgress.message && (
        <Alert type="error" showIcon message={commandProgress.message} style={{ marginBottom: 12 }} />
      )}
      <div className="new-round-layout">
        <aside className="new-round-rail" data-testid="new-round-rail">
          <Steps
            direction="vertical"
            size="small"
            current={TASK_ORDER.indexOf(task)}
            items={TASK_ORDER.map((key) => ({ title: TASK_TITLES[key] }))}
          />
        </aside>
        <main className="new-round-content">
          {task === 'source' && (
            <ChangeSourceStep
              source={source}
              onChange={setSource}
              onNext={() => setTask('inputs')}
              baseConfirmedId={baseConfirmedId}
              blocked={commandBlocked}
            />
          )}
          {task === 'inputs' && (
            <UpdateInputsStep
              source={source}
              actualRevisionId={actualRevisionId}
              onActualChange={setActualRevisionId}
              salesPlanVersionId={salesPlanVersionId}
              onSalesChange={setSalesPlanVersionId}
              activeSales={activeSales}
              inputGaps={inputGaps}
              inputFetching={inputAuthorityFetching}
              inputError={inputAuthorityError}
              onRetryInputs={retryInputAuthority}
              blocked={commandBlocked}
              onBack={() => setTask('source')}
              onNext={() => void enterScope()}
            />
          )}
          {task === 'scope' && (
            <ImpactScopeStep
              source={source}
              inputs={inputs}
              inputsIdentity={inputsIdentity}
              preflight={preflight.data}
              fetching={preflight.isFetching}
              error={preflight.isError || preflight.isRefetchError}
              inputFetching={inputAuthorityFetching}
              inputError={inputAuthorityError}
              planningYear={planningYear}
              basePlanVersionId={baseConfirmedId}
              baseProjection={baseProjection.data}
              baseFetching={baseProjection.isFetching}
              baseError={baseProjection.isError || baseProjection.isRefetchError}
              baseInvalid={baseProjectionInvalid}
              blocked={commandBlocked}
              onRetry={() => void preflight.refetch()}
              onRetryBase={() => void baseProjection.refetch()}
              onBack={() => setTask('inputs')}
              onNext={() => void enterGenerate()}
            />
          )}
          {task === 'generate-compare' && (
            <GenerateCompareStep
              source={source}
              inputs={inputs}
              inputsIdentity={inputsIdentity}
              preflight={preflight.data}
              fetching={preflight.isFetching}
              error={preflight.isError || preflight.isRefetchError}
              inputFetching={inputAuthorityFetching}
              inputError={inputAuthorityError}
              planningYear={planningYear}
              intentIdentity={intentIdentity}
              basePlanVersionId={baseConfirmedId}
              baseProjection={baseProjection.data}
              baseFetching={baseProjection.isFetching}
              baseError={baseProjection.isError || baseProjection.isRefetchError}
              commandProgress={commandProgress}
              onCommandProgress={setCommandProgress}
              onBack={() => setTask('scope')}
              onCompare={(left, right) => {
                if (!left) {
                  navigate('/v5/annual-overview')
                  return
                }
                navigate(`/what-if-compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`)
              }}
            />
          )}
        </main>
      </div>
    </div>
  )
}
