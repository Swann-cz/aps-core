import { useEffect, useMemo, useRef, useState } from 'react'
import { Alert, App as AntdApp, Button, Card, Descriptions, Popconfirm, Select, Space, Steps, Table, Tag, Typography } from 'antd'
import { DeleteOutlined, EyeOutlined, LockOutlined, RocketOutlined } from '@ant-design/icons'
import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { v6Api } from '../../api/v6'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { V6ConditionDrawer } from '../../components/V6ConditionDrawer'
import { VersionPreviewDrawer, type VersionPreviewKind } from '../../components/VersionPreviewDrawer'
import type { ActualRevision } from '../../types/api'
import type { V6CommandResult, V6ConditionComposerValue, V6FormalPPVersion, V6GenerationMode, V6SessionStartRequest } from '../../types/v6'
import { useV6Planning } from '../../app/V6PlanningContext'

const ALGORITHM_SLOTS = ['inventory_policy', 'monthly_pp_allocation', 'working_mode_selection', 'block_placement', 'welding_sequence', 'candidate_selection']

type Selection = {
  pr: string
  ws: string | null
  factory: string
  calendar: string
  initial: string
  wip: string
  actual: string
  fixMonths: string[]
  note: string
}

type PreviewState = { title: string; kind: VersionPreviewKind; cacheKey: string; load: () => Promise<unknown> } | null

type GenerationPhase = 'IDLE' | 'STARTING_SESSION' | 'SESSION_CREATED' | 'GENERATING_CANDIDATE' | 'RECONCILING_FAILURE' | 'CLEANED' | 'CLEANUP_UNCONFIRMED'

type GenerationFailure = {
  stage: 'START_SESSION' | 'GENERATE_CANDIDATE' | 'CLEANUP'
  message: string
  errorCode: string | null
  errors: string[]
  problems: string[]
  missingInformation: string[]
  hardErrorCodes: string[]
  sessionId: string | null
  planningRevision: number | null
  httpStatus: number | null
  cleanupState: string | null
  cleanupMessage: string | null
}

type CleanupResolution = {
  kind: 'RECOVERED_CANDIDATE' | 'CLEANED' | 'UNCONFIRMED'
  message: string
}

class WizardGenerationError extends Error {
  failure: GenerationFailure

  constructor(failure: GenerationFailure) {
    super(failure.message)
    this.name = 'WizardGenerationError'
    this.failure = failure
  }
}

const emptySelection: Selection = { pr: '', ws: null, factory: '', calendar: '', initial: '', wip: '', actual: '', fixMonths: [], note: '' }

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function firstValue(sources: (Record<string, unknown> | null)[], key: string): unknown {
  for (const source of sources) {
    if (source && source[key] !== undefined && source[key] !== null) return source[key]
  }
  return undefined
}

function listText(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    if (typeof item === 'string') return item
    const row = asRecord(item)
    if (row) {
      const code = text(row.code || row.error_code || row.issue_type)
      const detail = text(row.detail || row.message)
      if (code && detail) return `${code}：${detail}`
      if (code || detail) return code || detail
    }
    try {
      return JSON.stringify(item)
    } catch {
      return String(item)
    }
  })
}

function problemText(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => {
    const row = asRecord(item)
    if (!row) return typeof item === 'string' ? item : String(item)
    const scope = [
      text(row.date) || text(row.month),
      text(row.typeclass_id),
      text(row.node_id),
    ].filter(Boolean).join(' / ')
    const quantityValues = [row.required, row.realizable, row.gap]
    const hasMeaningfulQuantities = quantityValues.some((item) => (
      item !== undefined && item !== null && Number(item) !== 0
    ))
    const quantities = hasMeaningfulQuantities ? [
      row.required !== undefined ? `需求 ${text(row.required)}` : '',
      row.realizable !== undefined ? `可实现 ${text(row.realizable)}` : '',
      row.gap !== undefined ? `缺口 ${text(row.gap)}` : '',
    ].filter(Boolean).join('，') : ''
    const detail = text(row.detail || row.message || row.code || row.issue_type)
    const source = [
      row.field ? `字段 ${text(row.field)}` : '',
      row.source_cell ? `来源 ${text(row.source_cell)}` : '',
    ].filter(Boolean).join('，')
    return [scope ? `[${scope}]` : '', quantities, detail, source]
      .filter(Boolean)
      .join(' · ')
  })
}

function failureFrom(reason: unknown, stage: GenerationFailure['stage'], fallbackSessionId: string | null = null): GenerationFailure {
  const apiDetail = reason instanceof ApiError ? asRecord(reason.detail) : null
  const result = asRecord(reason)
  const nested = asRecord(apiDetail?.detail) || asRecord(result?.detail)
  const payload = asRecord(nested?.payload) || asRecord(apiDetail?.payload) || asRecord(result?.payload)
  const rootErrorRaw = nested?.root_error ?? payload?.root_error ?? apiDetail?.root_error ?? result?.root_error
  const rootError = asRecord(rootErrorRaw)
  const sources = [rootError, nested, payload, apiDetail, result]
  const cleanup = asRecord(firstValue(sources, 'session_cleanup'))
  const cleanupRaw = firstValue(sources, 'session_cleanup')
  const rawRevision = firstValue(sources, 'planning_revision')
  const parsedRevision = Number(rawRevision)
  const detailValue = firstValue(sources, 'detail')
  const message = text(firstValue(sources, 'message'))
    || (typeof detailValue === 'string' ? detailValue : '')
    || (typeof rootErrorRaw === 'string' ? rootErrorRaw : '')
    || (reason instanceof Error ? reason.message : '')
    || 'V6.1.4 排产命令失败'
  return {
    stage,
    message,
    errorCode: text(firstValue(sources, 'error_code')) || null,
    errors: listText(firstValue(sources, 'errors')),
    problems: problemText(firstValue(sources, 'problems')),
    missingInformation: listText(firstValue(sources, 'missing_information')),
    hardErrorCodes: listText(firstValue(sources, 'hard_error_codes')),
    sessionId: text(firstValue(sources, 'session_id')) || fallbackSessionId,
    planningRevision: Number.isFinite(parsedRevision) ? parsedRevision : null,
    httpStatus: reason instanceof ApiError ? reason.status : null,
    cleanupState: text(cleanup?.status || cleanup?.state || cleanup?.outcome || cleanupRaw) || null,
    cleanupMessage: text(cleanup?.message || cleanup?.detail) || null,
  }
}

function monthsInParentHorizon(parent: V6FormalPPVersion | null): string[] {
  if (!parent) return []
  const start = /^(\d{4})-(\d{2})/.exec(parent.plan.horizon_start)
  const end = /^(\d{4})-(\d{2})/.exec(parent.plan.horizon_end)
  if (!start || !end) return []
  let year = Number(start[1])
  let month = Number(start[2])
  const endValue = Number(end[1]) * 12 + Number(end[2]) - 1
  const result: string[] = []
  while (year * 12 + month - 1 <= endValue && result.length < 240) {
    result.push(`${year}-${String(month).padStart(2, '0')}`)
    month += 1
    if (month === 13) {
      month = 1
      year += 1
    }
  }
  return result
}

function actualCutoff(actual: ActualRevision): string {
  return String(actual.actual_effective_date || actual.effective_date || '').slice(0, 10)
}

function allowedFixMonths(months: string[], actual: ActualRevision | null): string[] {
  if (!actual) return []
  const cutoff = actualCutoff(actual)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(cutoff)) return []
  return months.filter((month) => `${month}-01` > cutoff)
}

function formalModeLabel(formal: V6FormalPPVersion): string {
  return formal.input_bundle.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产' : 'Rolling'
}

function formalOptionLabel(formal: V6FormalPPVersion): string {
  return `${formal.display_name} · ${formalModeLabel(formal)} · ${formal.saved_at}`
}

function formalDisplayName(formals: V6FormalPPVersion[], formalId: string | null | undefined): string {
  return formals.find((formal) => formal.formal_pp_id === formalId)?.display_name || 'Formal 详情中查看'
}

function actualOptionLabel(actual: ActualRevision & { business_id?: string }, formals: V6FormalPPVersion[]): string {
  const version = actual.schema_version === 2 ? 'V2' : 'V1'
  const source = actual.source_formal_pp_id ? ` · ${formalDisplayName(formals, actual.source_formal_pp_id)}` : ''
  return `${actualCutoff(actual)} · ${actual.actual_revision_id.slice(0, 8)} · ${version}${source}`
}

function actualMatchesParent(actual: ActualRevision, parent: V6FormalPPVersion | null): boolean {
  if (!parent) return false
  if (actual.schema_version !== 2) return true
  return actual.source_formal_pp_id === parent.formal_pp_id
    && actual.source_formal_fingerprint === parent.formal_fingerprint
}

function actualWithinParentHorizon(actual: ActualRevision, parent: V6FormalPPVersion | null): boolean {
  if (!parent) return false
  const cutoff = actualCutoff(actual)
  return /^\d{4}-\d{2}-\d{2}$/.test(cutoff)
    && cutoff >= parent.plan.horizon_start.slice(0, 10)
    && cutoff <= parent.plan.horizon_end.slice(0, 10)
}

function text(value: unknown): string {
  return value === undefined || value === null ? '' : String(value)
}

function dateText(value: unknown): string {
  return text(value).replace(/-/g, '/') || '未指定日期'
}

function rangeText(params: Record<string, unknown>): string {
  return `${dateText(params.start_date)}—${dateText(params.end_date)}`
}

function workshopsText(value: unknown): string {
  return Array.isArray(value) && value.length ? value.map(text).join('、') : '全厂'
}

function workingModeText(value: unknown): string {
  return text(value)
    .replace('SINGLE_', '')
    .replace('8P2', '8+2')
    .replace('8P1', '8+1')
    .replace('8H', '8 小时') || '未指定模式'
}

function conditionSummary(value: V6ConditionComposerValue): string {
  const params = value.params
  const scope = workshopsText(params.workshop_ids)
  switch (value.selectorId) {
    case 'SHUTDOWN':
      return `计划性强制停线 · ${scope} · ${rangeText(params)}`
    case 'CAPACITY_LOSS':
      return `产能损失 · ${scope} · ${rangeText(params)} · 可用工时 ${text(params.available_hours_ceiling)} 小时`
    case 'ENABLE_SATURDAY':
      return `启用周六生产 · ${scope} · ${rangeText(params)}`
    case 'ENABLE_WORKING_MODE':
      return `启用工作模式 · ${scope} · ${workingModeText(params.working_mode_id)} · ${rangeText(params)}`
    case 'FORBID_WORKING_MODE':
      return `禁止工作模式 · ${scope} · ${workingModeText(params.working_mode_id)} · ${rangeText(params)}`
    case 'RAMP_UP':
      return `复线爬坡 · ${scope} · ${rangeText(params)} · JPH ${Array.isArray(params.daily_jph_ceilings) ? params.daily_jph_ceilings.join('→') : text(params.daily_jph_ceilings)}`
    case 'WBS_LEVEL':
      return `WBS 水位 · ${rangeText(params)} · 目标 ${text(params.water_level)}`
    case 'WIP_TARGET_OVERRIDE':
      return `短期 WIP 目标 · ${text(params.node_type)}/${text(params.node_id)} · ${rangeText(params)} · 目标 ${text(params.target_quantity)}`
    case 'MANUAL_FILLING_ADJUSTMENT':
      return `单日指定产量 · ${text(params.workshop_id) || '未指定车间'} · ${dateText(params.date)} · OUT ${text(params.out)} 台`
    case 'MANUAL_FILLING_BATCH':
      return `批量指定产量 · 共 ${Array.isArray(params.items) ? params.items.length : 0} 项`
    case 'AVOID_SATURDAY':
      return `尽量少用周六 · ${scope} · ${rangeText(params)} · 最多 ${text(params.used_saturday_days)} 天 · 优先级 ${text(params.priority_tier)}`
    default:
      return '未识别的排产条件'
  }
}

export function V6PlanningWizard({ mode }: { mode: V6GenerationMode }) {
  const { message } = AntdApp.useApp()
  const rolling = mode === 'ROLLING_FROM_FORMAL_PP'
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const requestedActualId = rolling ? searchParams.get('actual_revision_id') : null
  const requestedSourceFormalId = rolling ? searchParams.get('source_formal_pp_id') : null
  const queryClient = useQueryClient()
  const v6State = useV6Planning()
  const [step, setStep] = useState(0)
  const [selection, setSelection] = useState<Selection>(emptySelection)
  const [parentId, setParentId] = useState('')
  const [inputsConfirmed, setInputsConfirmed] = useState(false)
  const [initialized, setInitialized] = useState(false)
  const [preview, setPreview] = useState<PreviewState>(null)
  const [conditionOpen, setConditionOpen] = useState(false)
  const [conditions, setConditions] = useState<{ value: V6ConditionComposerValue; canonical: Record<string, unknown>[] }[]>([])
  const [generationPhase, setGenerationPhase] = useState<GenerationPhase>('IDLE')
  const [generationFailure, setGenerationFailure] = useState<GenerationFailure | null>(null)
  const [prefillError, setPrefillError] = useState<string | null>(null)
  const appliedParentIdRef = useRef<string | null>(null)
  const appliedActualPrefillRef = useRef<string | null>(null)

  const prQuery = useQuery({ queryKey: ['v6', 'pr'], queryFn: v6Api.prVersions })
  const wsQuery = useQuery({ queryKey: ['v6', 'ws'], queryFn: v6Api.wsVersions })
  const factoryQuery = useQuery({ queryKey: ['v6', 'factory'], queryFn: v6Api.factoryVersions })
  const calendarQuery = useQuery({ queryKey: ['v6', 'calendar'], queryFn: v6Api.calendarVersions })
  const initialQuery = useQuery({ queryKey: ['v6', 'initial'], queryFn: v6Api.initialStateVersions })
  const wipQuery = useQuery({ queryKey: ['v6', 'wip'], queryFn: v6Api.wipPolicyVersions })
  const actualQuery = useQuery({ queryKey: ['v6', 'actual'], queryFn: v6Api.actualRevisions })
  const formalQuery = useQuery({ queryKey: ['v6', 'formal'], queryFn: v6Api.formalVersions })
  const algorithmQueries = useQueries({ queries: ALGORITHM_SLOTS.map((slot) => ({ queryKey: ['v6', 'algorithm', slot], queryFn: () => v6Api.algorithmOptions(slot) })) })
  const loading = [prQuery, wsQuery, factoryQuery, calendarQuery, initialQuery, wipQuery, actualQuery, formalQuery].some((query) => query.isLoading)
  const error = [prQuery, wsQuery, factoryQuery, calendarQuery, initialQuery, wipQuery, actualQuery, formalQuery].find((query) => query.error)?.error
  const parent = (formalQuery.data || []).find((item) => item.formal_pp_id === parentId) || null
  const horizonMonths = useMemo(() => monthsInParentHorizon(parent), [parent])
  const selectedActual = (actualQuery.data || []).find((item) => item.actual_revision_id === selection.actual) || null
  const fixMonthOptions = useMemo(
    () => allowedFixMonths(horizonMonths, selectedActual),
    [horizonMonths, selectedActual],
  )
  const fixMonthKey = fixMonthOptions.join('|')
  const legalActuals = useMemo(
    () => (actualQuery.data || []).filter((item) => (
      actualMatchesParent(item, parent)
      && actualWithinParentHorizon(item, parent)
    )),
    [actualQuery.data, parent],
  )
  const legalActualKey = legalActuals.map((item) => item.actual_revision_id).join('|')
  const sourceRestrictedFormalId = selectedActual?.schema_version === 2
    ? selectedActual.source_formal_pp_id || null
    : requestedActualId && appliedActualPrefillRef.current !== requestedActualId
      ? requestedSourceFormalId
      : null
  const selectableFormalVersions = (formalQuery.data || []).filter((item) => !sourceRestrictedFormalId || item.formal_pp_id === sourceRestrictedFormalId)
  const sourceRestrictedFormalName = sourceRestrictedFormalId
    ? formalDisplayName(formalQuery.data || [], sourceRestrictedFormalId)
    : null
  const actualPartition = selectedActual && parent ? {
    actual: `${parent.plan.horizon_start.slice(0, 10)} ～ ${actualCutoff(selectedActual)}`,
    mutable: dayjs(actualCutoff(selectedActual)).add(1, 'day').format('YYYY-MM-DD') <= dayjs(actualCutoff(selectedActual)).endOf('month').format('YYYY-MM-DD')
      ? `${dayjs(actualCutoff(selectedActual)).add(1, 'day').format('YYYY-MM-DD')} ～ ${dayjs(actualCutoff(selectedActual)).endOf('month').format('YYYY-MM-DD')}`
      : '无（截止日为月末）',
  } : null
  const parentConditions = rolling
    ? parent?.input_bundle.condition_snapshot.items || []
    : []
  const addedConditions = conditions.flatMap((item) => item.canonical)
  const rollingConditions = addedConditions.length
    ? [...parentConditions, ...addedConditions]
    : undefined

  useEffect(() => {
    if (rolling || initialized || loading) return
    setSelection({
      ...emptySelection,
      pr: prQuery.data?.find((item) => item.status === 'ACTIVE')?.pr_version_id || '',
      ws: wsQuery.data?.find((item) => item.status === 'ACTIVE')?.ws_version_id || null,
      factory: factoryQuery.data?.find((item) => item.status === 'ACTIVE')?.factory_model_version_id || '',
      calendar: calendarQuery.data?.find((item) => item.status === 'ACTIVE')?.calendar_version_id || '',
      initial: initialQuery.data?.find((item) => item.status === 'ACTIVE')?.initial_state_snapshot_id || '',
      wip: wipQuery.data?.find((item) => item.status === 'ACTIVE')?.wip_target_version_id || '',
    })
    setInitialized(true)
  }, [calendarQuery.data, factoryQuery.data, initialQuery.data, initialized, loading, prQuery.data, rolling, wipQuery.data, wsQuery.data])

  useEffect(() => {
    if (!rolling || !parent) return
    if (appliedParentIdRef.current === parent.formal_pp_id) return
    appliedParentIdRef.current = parent.formal_pp_id
    setSelection((current) => ({
      ...current,
      pr: '',
      ws: parent.input_bundle.ws_version_id,
      factory: parent.input_bundle.factory_version_id,
      calendar: parent.input_bundle.calendar_version_id,
      initial: parent.input_bundle.initial_state_version_id,
      wip: parent.input_bundle.wip_policy_version_id,
      actual: '',
      fixMonths: [],
      note: `基于 ${parent.display_name} 的 Rolling`,
    }))
    setGenerationFailure(null)
    setGenerationPhase('IDLE')
    setInputsConfirmed(false)
  }, [parent, rolling])

  useEffect(() => {
    if (!rolling || !requestedActualId || loading || appliedActualPrefillRef.current === requestedActualId) return
    const actual = (actualQuery.data || []).find((item) => item.actual_revision_id === requestedActualId)
    if (!actual) {
      setPrefillError(`未找到指定 ActualRevision：${requestedActualId}`)
      appliedActualPrefillRef.current = requestedActualId
      return
    }
    const sourceFormalId = actual.schema_version === 2 ? actual.source_formal_pp_id : requestedSourceFormalId
    if (!sourceFormalId) {
      setPrefillError('指定 Actual 缺少可验证的 source Formal，不能自动进入 V6.1.4 Rolling。')
      appliedActualPrefillRef.current = requestedActualId
      return
    }
    if (requestedSourceFormalId && requestedSourceFormalId !== sourceFormalId) {
      setPrefillError('URL 中的 source Formal 与 ActualRevision 身份不一致，已停止自动选择。')
      appliedActualPrefillRef.current = requestedActualId
      return
    }
    const sourceFormal = (formalQuery.data || []).find((item) => item.formal_pp_id === sourceFormalId)
    if (!sourceFormal || (actual.schema_version === 2 && actual.source_formal_fingerprint !== sourceFormal.formal_fingerprint)) {
      setPrefillError('ActualRevision 的 source Formal 或 fingerprint 无法与 Formal 库匹配，已停止自动选择。')
      appliedActualPrefillRef.current = requestedActualId
      return
    }
    if (parentId !== sourceFormalId) {
      setParentId(sourceFormalId)
      return
    }
    if (appliedParentIdRef.current !== sourceFormalId) return
    setSelection((current) => ({ ...current, actual: requestedActualId, fixMonths: [] }))
    setStep(1)
    setPrefillError(null)
    appliedActualPrefillRef.current = requestedActualId
  }, [actualQuery.data, formalQuery.data, loading, parentId, requestedActualId, requestedSourceFormalId, rolling])

  useEffect(() => {
    if (!rolling || !selection.actual) return
    const allowed = new Set(fixMonthOptions)
    const next = selection.fixMonths.filter((month) => allowed.has(month))
    if (next.length === selection.fixMonths.length) return
    setSelection((current) => ({ ...current, fixMonths: next }))
    setGenerationFailure(null)
    setGenerationPhase('IDLE')
    setInputsConfirmed(false)
  }, [fixMonthKey, rolling, selection.actual, selection.fixMonths])

  useEffect(() => {
    if (!rolling || !selection.actual) return
    if (legalActuals.some((item) => item.actual_revision_id === selection.actual)) return
    setSelection((current) => ({ ...current, actual: '', fixMonths: [] }))
    setGenerationFailure(null)
    setGenerationPhase('IDLE')
    setInputsConfirmed(false)
  }, [legalActualKey, rolling, selection.actual])

  const update = <K extends keyof Selection>(key: K, value: Selection[K]) => {
    setSelection((current) => ({ ...current, [key]: value }))
    setGenerationFailure(null)
    setGenerationPhase('IDLE')
    setInputsConfirmed(false)
  }

  const updateActual = (actualRevisionId: string) => {
    const nextActual = (actualQuery.data || []).find(
      (item) => item.actual_revision_id === actualRevisionId,
    ) || null
    const nextAllowed = new Set(allowedFixMonths(horizonMonths, nextActual))
    setSelection((current) => ({
      ...current,
      actual: actualRevisionId,
      fixMonths: current.fixMonths.filter((month) => nextAllowed.has(month)),
    }))
    setGenerationFailure(null)
    setGenerationPhase('IDLE')
    setInputsConfirmed(false)
  }

  const defaultAlgorithmProfile = useMemo(() => {
    if (algorithmQueries.some((query) => !query.data?.[0])) return null
    return Object.fromEntries([
      ['profile_id', 'default-v1'],
      ['profile_version', '1'],
      ...ALGORITHM_SLOTS.map((slot, index) => [slot, algorithmQueries[index].data![0]]),
    ])
  }, [algorithmQueries])

  const selectedActualIsLegal = Boolean(
    selectedActual
    && legalActuals.some((item) => item.actual_revision_id === selectedActual.actual_revision_id),
  )
  const fixMonthsAreLegal = selection.fixMonths.every((month) => fixMonthOptions.includes(month))
  const requiredReady = rolling
    ? Boolean(parent && selection.pr && selectedActualIsLegal && fixMonthsAreLegal && selection.factory && selection.calendar && selection.initial && selection.wip)
    : Boolean(selection.pr && selection.factory && selection.calendar && selection.initial && selection.wip)

  const invalidateV6State = async () => {
    await Promise.allSettled([
      queryClient.invalidateQueries({ queryKey: ['v6', 'sessions'] }),
      queryClient.invalidateQueries({ queryKey: ['v6', 'workbench'] }),
    ])
  }

  const reconcileFailedSession = async (
    sessionId: string,
    fallbackRevision: number,
    failure: GenerationFailure,
  ): Promise<CleanupResolution> => {
    setGenerationPhase('RECONCILING_FAILURE')
    try {
      const session = await v6Api.session(sessionId)
      if (session.current_candidate_id) {
        return {
          kind: 'RECOVERED_CANDIDATE',
          message: '后端已生成 Candidate；当前请求仅丢失了成功响应。',
        }
      }
      if (session.status === 'ABANDONED' || session.status === 'CLOSED') {
        return {
          kind: 'CLEANED',
          message: `空 Session 已处于 ${session.status} 状态。`,
        }
      }
      if (session.status !== 'OPEN') {
        return {
          kind: 'UNCONFIRMED',
          message: `Session 状态 ${session.status} 无法自动清理。`,
        }
      }
      const currentRevision = session.planning_revision ?? fallbackRevision
      if (currentRevision > 0) {
        return {
          kind: 'UNCONFIRMED',
          message: `Session rev.${currentRevision} 已发生后续变化，前端不会自动 abandon。`,
        }
      }

      let abandonFailure: GenerationFailure
      try {
        const abandoned = await v6Api.abandonSession(sessionId, currentRevision)
        if (abandoned.outcome === 'SESSION_ABANDONED') {
          return {
            kind: 'CLEANED',
            message: '候选生成失败后留下的空 Session 已清理。',
          }
        }
        abandonFailure = failureFrom(abandoned, 'CLEANUP', sessionId)
      } catch (reason) {
        abandonFailure = failureFrom(reason, 'CLEANUP', sessionId)
      }

      try {
        const latest = await v6Api.session(sessionId)
        if (latest.current_candidate_id) {
          return {
            kind: 'RECOVERED_CANDIDATE',
            message: 'abandon 竞态期间后端已生成 Candidate。',
          }
        }
        if (latest.status === 'ABANDONED' || latest.status === 'CLOSED') {
          return {
            kind: 'CLEANED',
            message: `abandon 结果复查确认 Session 已 ${latest.status}。`,
          }
        }
        if (latest.status === 'OPEN' && latest.planning_revision === currentRevision) {
          try {
            const retried = await v6Api.abandonSession(sessionId, currentRevision)
            if (retried.outcome === 'SESSION_ABANDONED') {
              return {
                kind: 'CLEANED',
                message: '首次 abandon 未确认，复查后以同一 rev.0 完成一次 CAS 重试并清理。',
              }
            }
            const retryFailure = failureFrom(retried, 'CLEANUP', sessionId)
            return {
              kind: 'UNCONFIRMED',
              message: `${retryFailure.errorCode ? `${retryFailure.errorCode}：` : ''}${retryFailure.message}；同一 rev.0 的单次 CAS 重试未成功。`,
            }
          } catch (retryReason) {
            const retryFailure = failureFrom(retryReason, 'CLEANUP', sessionId)
            return {
              kind: 'UNCONFIRMED',
              message: `${retryFailure.errorCode ? `${retryFailure.errorCode}：` : ''}${retryFailure.message}；同一 rev.0 的单次 CAS 重试未成功。`,
            }
          }
        }
        return {
          kind: 'UNCONFIRMED',
          message: `${abandonFailure.errorCode ? `${abandonFailure.errorCode}：` : ''}${abandonFailure.message}；复查状态 ${latest.status} rev.${latest.planning_revision}，不再重试 abandon。`,
        }
      } catch (secondReason) {
        const reportedCleanup = String(failure.cleanupState || '').toUpperCase()
        if (reportedCleanup.includes('ABANDONED') || reportedCleanup.includes('CLOSED')) {
          return {
            kind: 'CLEANED',
            message: failure.cleanupMessage || `后端已报告 Session ${failure.cleanupState}。`,
          }
        }
        const secondFailure = failureFrom(secondReason, 'CLEANUP', sessionId)
        return {
          kind: 'UNCONFIRMED',
          message: `${abandonFailure.errorCode ? `${abandonFailure.errorCode}：` : ''}${abandonFailure.message}；二次状态复查失败：${secondFailure.message}`,
        }
      }
    } catch (reason) {
      const reportedCleanup = String(failure.cleanupState || '').toUpperCase()
      if (reportedCleanup.includes('ABANDONED') || reportedCleanup.includes('CLOSED')) {
        return {
          kind: 'CLEANED',
          message: failure.cleanupMessage || `后端已报告 Session ${failure.cleanupState}。`,
        }
      }
      const cleanupFailure = failureFrom(reason, 'CLEANUP', sessionId)
      return {
        kind: 'UNCONFIRMED',
        message: `${cleanupFailure.errorCode ? `${cleanupFailure.errorCode}：` : ''}${cleanupFailure.message}`,
      }
    } finally {
      await invalidateV6State()
    }
  }

  const generate = useMutation({
    mutationFn: async () => {
      if (!inputsConfirmed || !requiredReady) throw new Error('请先确认完整输入版本')
      setGenerationFailure(null)
      setGenerationPhase('STARTING_SESSION')
      const body: V6SessionStartRequest = {
        generation_mode: mode,
        pr_version_id: selection.pr,
        ws_version_id: selection.ws,
        parent_formal_pp_id: rolling ? parentId : null,
        factory_version_id: selection.factory,
        calendar_version_id: selection.calendar,
        initial_state_version_id: selection.initial,
        wip_policy_version_id: selection.wip,
        actual_revision_id: rolling ? selection.actual : null,
        planning_conditions: rolling ? rollingConditions : addedConditions,
        algorithm_profile: rolling ? undefined : defaultAlgorithmProfile,
        fix_months: rolling ? selection.fixMonths : [],
        work_note: selection.note || (rolling ? 'V6.1.4 Rolling' : 'V6.1.4 初始排产'),
      }
      let started: V6CommandResult
      try {
        started = await v6Api.startSession(body)
      } catch (reason) {
        throw new WizardGenerationError(failureFrom(reason, 'START_SESSION'))
      }
      if (started.outcome !== 'SESSION_STARTED' || !started.session_id) {
        throw new WizardGenerationError(failureFrom(started, 'START_SESSION'))
      }
      const sessionId = started.session_id
      const sessionRevision = started.planning_revision || 0
      setGenerationPhase('SESSION_CREATED')
      try {
        setGenerationPhase('GENERATING_CANDIDATE')
        const candidate = await v6Api.generateCandidate(sessionId, sessionRevision)
        if (candidate.outcome !== 'DRAFT_CANDIDATE_CREATED') {
          throw new WizardGenerationError(
            failureFrom(candidate, 'GENERATE_CANDIDATE', sessionId),
          )
        }
      } catch (reason) {
        const failure = reason instanceof WizardGenerationError
          ? reason.failure
          : failureFrom(reason, 'GENERATE_CANDIDATE', sessionId)
        const cleanup = await reconcileFailedSession(
          sessionId,
          failure.planningRevision ?? sessionRevision,
          failure,
        )
        if (cleanup.kind === 'RECOVERED_CANDIDATE') {
          return sessionId
        }
        setGenerationPhase(
          cleanup.kind === 'CLEANED' ? 'CLEANED' : 'CLEANUP_UNCONFIRMED',
        )
        throw new WizardGenerationError({
          ...failure,
          sessionId,
          cleanupState: cleanup.kind,
          cleanupMessage: cleanup.message,
        })
      }
      return sessionId
    },
    onSuccess: async (sessionId) => {
      setGenerationPhase('IDLE')
      setGenerationFailure(null)
      message.success('V6.1.4 DraftCandidate 已生成')
      await invalidateV6State()
      navigate(`/v6/session/${sessionId}`)
    },
    onError: async (reason) => {
      const failure = reason instanceof WizardGenerationError
        ? reason.failure
        : failureFrom(reason, 'START_SESSION')
      setGenerationFailure(failure)
      setGenerationPhase(
        failure.cleanupState === 'CLEANED'
          ? 'CLEANED'
          : failure.sessionId
            ? 'CLEANUP_UNCONFIRMED'
            : 'IDLE',
      )
      await invalidateV6State()
      message.error(failure.message)
    },
  })

  const retryCleanup = async () => {
    if (!generationFailure?.sessionId) return
    const resolution = await reconcileFailedSession(
      generationFailure.sessionId,
      generationFailure.planningRevision ?? 0,
      generationFailure,
    )
    if (resolution.kind === 'RECOVERED_CANDIDATE') {
      setGenerationFailure(null)
      setGenerationPhase('IDLE')
      navigate(`/v6/session/${generationFailure.sessionId}`)
      return
    }
    setGenerationPhase(
      resolution.kind === 'CLEANED' ? 'CLEANED' : 'CLEANUP_UNCONFIRMED',
    )
    setGenerationFailure((current) => current ? {
      ...current,
      cleanupState: resolution.kind,
      cleanupMessage: resolution.message,
    } : current)
  }

  if (loading) return <PageState kind="loading" rows={7} />
  if (error) return <PageState kind="system-error" error={error} onRetry={() => window.location.reload()} />
  if (v6State.multipleOpenSessions) return <PageState kind="business-blocked" title="检测到多个开放 V6.1.4 Session" reasons={['请先处理 Session 数据冲突，前端不会继续创建新会话。']} />
  const ownsUnconfirmedSession = Boolean(
    v6State.activeSession
    && generationPhase === 'CLEANUP_UNCONFIRMED'
    && generationFailure?.sessionId === v6State.activeSession.session_id,
  )
  if (v6State.activeSession && !ownsUnconfirmedSession) return <PageState kind="business-blocked" title="已有进行中的 V6.1.4 排产" reasons={[`Session ${v6State.activeSession.session_id} · rev.${v6State.activeSession.planning_revision}`]} action={<Button type="primary" onClick={() => navigate(`/v6/session/${v6State.activeSession!.session_id}`)}>继续当前排产</Button>} />

  const activeLabel = (items: any[], idField: string, value: string | null) => {
    if (!value) return 'NOT_EVALUATED'
    const item = items.find((entry) => entry[idField] === value)
    return item ? [item.display_name, item.calendar_year ?? item.planning_year, item.status, item.created_at].filter(Boolean).join(' · ') : '版本不可用'
  }
  const selectOptions = (items: any[], idField: string) => items.map((item) => ({ value: item[idField], label: [item.display_name, item.calendar_year ?? item.planning_year, item.status, item.created_at].filter(Boolean).join(' · ') }))
  const previewButton = (title: string, kind: VersionPreviewKind, cacheKey: string, load: (() => Promise<unknown>) | null) => <Button size="small" icon={<EyeOutlined />} disabled={!load} onClick={() => load && setPreview({ title, kind, cacheKey, load })}>预览</Button>

  const initialRows = [
    { key: 'pr', label: 'PR Version *', value: selection.pr, options: selectOptions(prQuery.data || [], 'pr_version_id'), preview: selection.pr ? () => v6Api.prVersion(selection.pr) : null },
    { key: 'ws', label: 'WS Version', value: selection.ws, options: [{ value: '', label: '不选择 · NOT_EVALUATED' }, ...selectOptions(wsQuery.data || [], 'ws_version_id')], preview: selection.ws ? () => v6Api.wsVersion(selection.ws!) : null },
    { key: 'factory', label: 'Factory *', value: selection.factory, options: selectOptions(factoryQuery.data || [], 'factory_model_version_id'), preview: selection.factory ? () => v6Api.factoryVersion(selection.factory) : null },
    { key: 'calendar', label: 'Calendar *', value: selection.calendar, options: selectOptions(calendarQuery.data || [], 'calendar_version_id'), preview: selection.calendar ? () => v6Api.calendarVersion(selection.calendar) : null },
    { key: 'initial', label: 'Initial State *', value: selection.initial, options: selectOptions(initialQuery.data || [], 'initial_state_snapshot_id'), preview: selection.initial ? () => v6Api.initialStateVersion(selection.initial) : null },
    { key: 'wip', label: 'WIP Policy *', value: selection.wip, options: selectOptions(wipQuery.data || [], 'wip_target_version_id'), preview: selection.wip ? () => v6Api.wipPolicyVersion(selection.wip) : null },
    { key: 'algorithm', label: 'Algorithm Profile *', value: 'default-v1', options: [{ value: 'default-v1', label: 'default-v1 · 六算法槽默认组合' }], preview: defaultAlgorithmProfile ? () => Promise.resolve(defaultAlgorithmProfile) : null, disabled: true },
  ]

  const rollingRows = parent ? [
    { key: 'pr', label: 'PR Version *', parent: activeLabel(prQuery.data || [], 'pr_version_id', parent.input_bundle.pr_version_id), active: activeLabel(prQuery.data || [], 'pr_version_id', prQuery.data?.find((item) => item.status === 'ACTIVE')?.pr_version_id || null), value: selection.pr, options: selectOptions(prQuery.data || [], 'pr_version_id'), preview: selection.pr ? () => v6Api.prVersion(selection.pr) : null },
    { key: 'ws', label: 'WS Version', parent: activeLabel(wsQuery.data || [], 'ws_version_id', parent.input_bundle.ws_version_id), active: activeLabel(wsQuery.data || [], 'ws_version_id', wsQuery.data?.find((item) => item.status === 'ACTIVE')?.ws_version_id || null), value: selection.ws || '', options: [{ value: '', label: 'NOT_EVALUATED' }, ...selectOptions(wsQuery.data || [], 'ws_version_id')], preview: selection.ws ? () => v6Api.wsVersion(selection.ws!) : null },
    { key: 'factory', label: 'Factory', parent: activeLabel(factoryQuery.data || [], 'factory_model_version_id', parent.input_bundle.factory_version_id), active: activeLabel(factoryQuery.data || [], 'factory_model_version_id', factoryQuery.data?.find((item) => item.status === 'ACTIVE')?.factory_model_version_id || null), value: selection.factory, options: selectOptions(factoryQuery.data || [], 'factory_model_version_id'), preview: selection.factory ? () => v6Api.factoryVersion(selection.factory) : null },
    { key: 'calendar', label: 'Calendar', parent: activeLabel(calendarQuery.data || [], 'calendar_version_id', parent.input_bundle.calendar_version_id), active: activeLabel(calendarQuery.data || [], 'calendar_version_id', calendarQuery.data?.find((item) => item.status === 'ACTIVE')?.calendar_version_id || null), value: selection.calendar, options: selectOptions(calendarQuery.data || [], 'calendar_version_id'), preview: selection.calendar ? () => v6Api.calendarVersion(selection.calendar) : null },
    { key: 'initial', label: 'Initial State', parent: activeLabel(initialQuery.data || [], 'initial_state_snapshot_id', parent.input_bundle.initial_state_version_id), active: activeLabel(initialQuery.data || [], 'initial_state_snapshot_id', initialQuery.data?.find((item) => item.status === 'ACTIVE')?.initial_state_snapshot_id || null), value: selection.initial, options: selectOptions(initialQuery.data || [], 'initial_state_snapshot_id'), preview: selection.initial ? () => v6Api.initialStateVersion(selection.initial) : null },
    { key: 'wip', label: 'WIP Policy', parent: activeLabel(wipQuery.data || [], 'wip_target_version_id', parent.input_bundle.wip_policy_version_id), active: activeLabel(wipQuery.data || [], 'wip_target_version_id', wipQuery.data?.find((item) => item.status === 'ACTIVE')?.wip_target_version_id || null), value: selection.wip, options: selectOptions(wipQuery.data || [], 'wip_target_version_id'), preview: selection.wip ? () => v6Api.wipPolicyVersion(selection.wip) : null },
    { key: 'algorithm', label: 'Algorithm Profile', parent: parent.input_bundle.algorithm_profile.profile_id, active: 'default-v1', value: parent.input_bundle.algorithm_profile.profile_id, options: [{ value: parent.input_bundle.algorithm_profile.profile_id, label: `${parent.input_bundle.algorithm_profile.profile_id} · 继承父 PP` }], preview: () => Promise.resolve(parent.input_bundle.algorithm_profile), disabled: true },
  ] : []

  const taskItems = rolling ? ['父正式 PP', '输入与继承', '可选排产条件', '检查并生成'] : ['输入版本', '排产条件', '检查并生成']
  return <div className="page-container v6-wizard-page">
    <PageHeader title={rolling ? 'V6.1.4 Rolling' : 'V6.1.4 初始排产'} subtitle={rolling ? '父正式 PP 为基线，所有替换必须显式完成' : '从完整输入包生成第一个 DraftCandidate'} />
    {prefillError && <Alert data-testid="rolling-actual-prefill-error" type="error" showIcon style={{ marginBottom: 14 }} message="Actual / Formal 身份预选失败" description={prefillError} />}
    <div className="v6-wizard-layout">
      <aside className="v6-wizard-rail"><Steps direction="vertical" current={step} items={taskItems.map((title, index) => ({ title, onClick: index <= step ? () => setStep(index) : undefined }))} /></aside>
      <main className="v6-wizard-content">
        {rolling && step === 0 && <Card title="选择父正式 PP">
          <Select data-testid="rolling-parent-formal" showSearch optionFilterProp="label" style={{ width: '100%' }} placeholder="选择 FormalPPVersion" value={parentId || undefined} onChange={(value) => {
            if (conditions.length) message.info('父正式 PP 已切换，本轮尚未提交的新增条件已清空。')
            setConditions([])
            setParentId(value)
            setStep(1)
          }} options={selectableFormalVersions.map((item) => ({ value: item.formal_pp_id, label: formalOptionLabel(item) }))} />
          {sourceRestrictedFormalName && <Alert data-testid="rolling-source-formal-lock" type="info" showIcon style={{ marginTop: 12 }} message="父 Formal 已受 Actual V2 来源约束" description={`只能使用 ${sourceRestrictedFormalName}；不能把 Formal A 的 Actual 绑定到 Formal B。`} />}
          {parent && <Descriptions bordered size="small" column={2} style={{ marginTop: 16 }}><Descriptions.Item label="模式">{parent.input_bundle.generation_mode}</Descriptions.Item><Descriptions.Item label="父 PP">{parent.parent_formal_pp_id ? formalDisplayName(formalQuery.data || [], parent.parent_formal_pp_id) : '—'}</Descriptions.Item><Descriptions.Item label="保存人">{parent.saved_by}</Descriptions.Item><Descriptions.Item label="保存时间">{parent.saved_at}</Descriptions.Item></Descriptions>}
        </Card>}

        {((!rolling && step === 0) || (rolling && step === 1)) && <Card title={rolling ? '输入与继承差异' : '确认输入版本'} extra={<Tag color={inputsConfirmed ? 'success' : 'warning'}>{inputsConfirmed ? '已确认' : '待确认'}</Tag>}>
          {!rolling ? <Table pagination={false} rowKey="key" dataSource={initialRows} columns={[
            { title: '输入项', dataIndex: 'label', width: 180, render: (value) => <strong>{value}</strong> },
            { title: '当前选择', render: (_, row: any) => <Select showSearch optionFilterProp="label" disabled={row.disabled} style={{ width: '100%' }} value={row.value ?? ''} options={row.options} onChange={(value) => update(row.key, row.key === 'ws' ? (value || null) : value)} /> },
            { title: '查看', width: 90, render: (_, row: any) => previewButton(row.label, row.key, String(row.value || 'none'), row.preview) },
          ]} /> : !parent ? <Alert type="warning" showIcon message="请先选择父正式 PP" /> : <Table pagination={false} rowKey="key" dataSource={rollingRows} columns={[
            { title: '输入项', dataIndex: 'label', width: 150, render: (value) => <strong>{value}</strong> },
            { title: '父 PP 绑定值', dataIndex: 'parent' },
            { title: '当前 Active', dataIndex: 'active' },
            { title: '本轮最终选择', render: (_, row: any) => <Space.Compact style={{ width: '100%' }}><Select showSearch optionFilterProp="label" disabled={row.disabled} style={{ width: '100%' }} value={row.value} options={row.options} placeholder={row.key === 'pr' ? '必须明确选择' : undefined} onChange={(value) => update(row.key, row.key === 'ws' ? (value || null) : value)} />{previewButton(row.label, row.key, String(row.value || 'none'), row.preview)}</Space.Compact> },
          ]} />}
          {rolling && <div className="v6-rolling-extra"><div><strong>Actual Revision *</strong><Space.Compact style={{ width: '100%', marginTop: 8 }}><Select data-testid="rolling-actual-revision" style={{ width: '100%' }} placeholder="选择 Actual" value={selection.actual || undefined} options={legalActuals.map((item) => ({ value: item.actual_revision_id, label: actualOptionLabel(item, formalQuery.data || []) }))} onChange={updateActual} />{previewButton('Actual Revision', 'actual', selection.actual || 'none', selection.actual ? () => v6Api.actualRevision(selection.actual) : null)}</Space.Compact></div><div><strong>未来 Fix 月份（可选）</strong><Select data-testid="rolling-fix-months" mode="multiple" disabled={!selectedActualIsLegal} style={{ width: '100%', marginTop: 8 }} value={selection.fixMonths} options={fixMonthOptions.map((month) => ({ value: month, label: month }))} onChange={(value) => update('fixMonths', value)} placeholder={selection.actual ? '可不选；选择后逐月冻结父 Formal' : '请先选择 Actual'} /></div>{actualPartition && <Descriptions data-testid="rolling-actual-partitions" bordered size="small" column={1} style={{ marginTop: 12 }}><Descriptions.Item label="ACTUALIZED（不可修改）">{actualPartition.actual}</Descriptions.Item><Descriptions.Item label="MUTABLE（截止月剩余）">{actualPartition.mutable}</Descriptions.Item><Descriptions.Item label="FIXED（人工选择完整月）">{selection.fixMonths.length ? selection.fixMonths.join('、') : '未选择（全部未来范围保持可变）'}</Descriptions.Item></Descriptions>}<Alert type="info" showIcon style={{ marginTop: 12 }} message="当前 Fix 为状态一致型" description="所选月份沿用父正式 PP 的月内决策，进入 Fix 月时的 WIP、Buffer 和 Glue/FIFO 边界也必须与父 PP 一致。Fix 前的可变区必须达到该边界，否则后端会阻断候选生成。" />{parent && legalActuals.length === 0 && <Alert type="error" showIcon style={{ marginTop: 12 }} message="没有符合父计划周期与来源 Formal 的 Actual" description="V2 Actual 必须来自当前父 Formal并落在其计划周期内；V1 保持原兼容路径。" />}{selection.actual && fixMonthOptions.length === 0 && <Alert type="info" showIcon style={{ marginTop: 12 }} message="所选 Actual 之后没有可 Fix 的完整月份" description="仍可继续 Rolling；系统不会建立 Fix 区。" />}</div>}
          <Alert
            type="info"
            showIcon
            style={{ marginTop: 16 }}
            message={rolling ? 'Rolling 输入继承规则' : '初始排产输入确认'}
            description={rolling
              ? 'Rolling 默认继承父正式 PP 绑定的版本。当前 Active 只用于对照，不会静默替换父 PP；选择替换版本表示本轮明确改变输入，仍需通过后端兼容校验。'
              : '当前 Active 版本只作为本次输入的预选值，生成 Session 前仍需人工确认完整输入包。PR / WS 业务 ID 中 SALES 后缀相同，表示来自同一个销售版本。'}
          />
          <Space style={{ marginTop: 16 }}><Button type="primary" icon={<LockOutlined />} disabled={!requiredReady} onClick={() => { setInputsConfirmed(true); setStep(rolling ? 2 : 1) }}>确认输入版本并继续</Button></Space>
        </Card>}

        {((!rolling && step === 1) || (rolling && step === 2)) && <Card title={rolling ? '可选排产条件' : '排产条件'} extra={<Button onClick={() => setConditionOpen(true)}>新增排产条件</Button>}>
          {rolling && <Alert
            type="info"
            showIcon
            message={`父 Formal 条件已继承：${parentConditions.length} 项`}
            description="父条件保持只读且不会在本页删除；本轮新增条件将在创建 Session 时追加到父条件之后。"
            style={{ marginBottom: 12 }}
          />}
          {conditions.length ? conditions.map((item, index) => <Alert
            key={`${item.value.selectorId}-${index}`}
            type="success"
            showIcon
            message={conditionSummary(item.value)}
            action={<Popconfirm
              title="删除这条排产条件？"
              description="仅从本轮尚未提交的条件列表中移除。"
              okText="删除"
              cancelText="取消"
              onConfirm={() => {
                setConditions((current) => current.filter((_condition, currentIndex) => currentIndex !== index))
                message.success('排产条件已删除')
              }}
            >
              <Button type="text" danger icon={<DeleteOutlined />}>删除</Button>
            </Popconfirm>}
            style={{ marginBottom: 8 }}
          />) : <Alert type="info" showIcon message="当前没有本轮新增条件" description={rolling ? (parentConditions.length > 0 ? '可以仅继承父 Formal 条件并直接继续，也可以先添加结构化条件。' : '父 Formal 没有排产条件，本轮也可以不新增条件直接继续。') : '可以直接使用基础设置生成，也可以先添加结构化条件。'} />}
          {rolling && <Alert type="info" showIcon style={{ marginTop: 12 }} message="AI 自然语言条件在首个 Candidate 后处理" description="生成首个 Candidate 后，可在统一工作台通过 ConditionDraft → Preview → 人工 Apply 添加 AI 条件。" />}
          <Space style={{ marginTop: 16 }}><Button type="primary" onClick={() => setStep(rolling ? 3 : 2)}>下一步：检查并生成</Button></Space>
        </Card>}

        {((!rolling && step === 2) || (rolling && step === 3)) && <Card title="检查并生成 DraftCandidate">
          <Alert type="warning" showIcon message="创建 Session 前会执行后端 Preflight" description="输入不完整、版本不兼容、物理容量冲突或 Actual/Lock 冲突会明确阻断，不会生成 Session。" />
          {generationFailure && <Alert
            type="error"
            showIcon
            style={{ marginTop: 12 }}
            message={`${generationFailure.errorCode ? `${generationFailure.errorCode} · ` : ''}${generationFailure.message}`}
            description={<div>
              <p style={{ margin: '0 0 4px' }}>失败阶段：{generationFailure.stage}</p>
              {generationFailure.errors.length > 0 && <p style={{ margin: '0 0 4px' }}>错误：{generationFailure.errors.join('；')}</p>}
              {generationFailure.problems.length > 0 && <p style={{ margin: '0 0 4px' }}>问题：{generationFailure.problems.join('；')}</p>}
              {generationFailure.missingInformation.length > 0 && <p style={{ margin: '0 0 4px' }}>缺少信息：{generationFailure.missingInformation.join('；')}</p>}
              {generationFailure.hardErrorCodes.length > 0 && <p style={{ margin: '0 0 4px' }}>硬错误：{generationFailure.hardErrorCodes.join('；')}</p>}
              {generationFailure.sessionId && <p style={{ margin: '0 0 4px' }}>Session：{generationFailure.sessionId}</p>}
              {generationFailure.cleanupMessage && <p style={{ margin: 0 }}>清理状态：{generationFailure.cleanupMessage}</p>}
            </div>}
            action={generationFailure.sessionId && generationPhase === 'CLEANUP_UNCONFIRMED'
              ? <Space direction="vertical"><Button size="small" onClick={() => void retryCleanup()}>重新检查并清理</Button><Button size="small" onClick={() => navigate(`/v6/session/${generationFailure.sessionId}`)}>打开 Session</Button></Space>
              : undefined}
          />}
          <Descriptions bordered size="small" column={2} style={{ marginTop: 16 }}>
            <Descriptions.Item label="模式">{mode}</Descriptions.Item><Descriptions.Item label="PR">{selection.pr || '未选择'}</Descriptions.Item><Descriptions.Item label="WS">{selection.ws || 'NOT_EVALUATED'}</Descriptions.Item><Descriptions.Item label="父 PP">{parentId || '—'}</Descriptions.Item><Descriptions.Item label="Fix 月份">{selection.fixMonths.join(', ') || '—'}</Descriptions.Item><Descriptions.Item label="输入确认">{inputsConfirmed ? '已确认' : '未确认'}</Descriptions.Item>
            {rolling && <><Descriptions.Item label="父条件">{parentConditions.length} 项</Descriptions.Item><Descriptions.Item label="本轮新增">{addedConditions.length} 项</Descriptions.Item><Descriptions.Item label="新 Session 条件总数" span={2}>{parentConditions.length + addedConditions.length} 项{addedConditions.length === 0 ? (parentConditions.length > 0 ? ' · 仅继承父 Formal 条件' : ' · 父 Formal 无条件，本轮未新增') : ''}</Descriptions.Item></>}
          </Descriptions>
          {rolling && <Alert type="info" showIcon style={{ marginTop: 12 }} message="Rolling Fix 边界" description={selection.fixMonths.length ? '已选择 Fix 月份：除月内决策外，进入 Fix 月时的 WIP、Buffer 和 Glue/FIFO 边界也必须与父正式 PP 一致。' : '本轮未选择 Fix 月份；Actual 截止日之后的未来范围保持可变，仍需通过其他后端物理与业务校验。'} />}
          <Button type="primary" size="large" icon={<RocketOutlined />} style={{ marginTop: 18 }} loading={generate.isPending || generationPhase === 'RECONCILING_FAILURE'} disabled={!inputsConfirmed || !requiredReady || generationPhase === 'CLEANUP_UNCONFIRMED' || generationPhase === 'RECONCILING_FAILURE'} onClick={() => generate.mutate()}>检查并生成候选</Button>
        </Card>}
      </main>
    </div>
    <VersionPreviewDrawer open={Boolean(preview)} title={preview?.title || ''} kind={preview?.kind || 'pr'} queryKey={['v6', 'preview', preview?.kind, preview?.cacheKey]} load={preview?.load || null} onClose={() => setPreview(null)} />
    <V6ConditionDrawer open={conditionOpen} planningYear={new Date().getFullYear()} factoryVersionId={selection.factory} initialValue={null} onClose={() => setConditionOpen(false)} applyLabel="加入本轮" onApply={async (value: V6ConditionComposerValue) => {
      const built = await api.buildCondition({
        ...(value.selectorType === 'INTENT'
          ? { intent_type: value.selectorId }
          : { action_type: value.selectorId }),
        params: value.params,
      })
      const canonical = built.planning_conditions
      if (!canonical?.length) throw new Error('后端没有返回可执行排产条件')
      setConditions((current) => [...current, { value, canonical }])
      setConditionOpen(false)
      message.success('排产条件已加入输入包')
    }} />
  </div>
}
