import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { useQuery, useQueryClient, type QueryObserverResult } from '@tanstack/react-query'
import { useLocation } from 'react-router-dom'
import { api } from '../api/planning'
import type { ManualEditItem, ManualFillingDraftScope, ManualFillingPreview, WorkbenchState } from '../types/api'
import { isV6FormalReadOnlyPath } from '../utils/v6FormalViewAuthority'

interface PlanningContextValue {
  session_id: string | null
  planning_revision: number | null
  current_plan_version_id: string | null
  factory: string | null
  planning_year: number | null
  month: string | null
  scenario: string | null
  available_months: string[]
  workbench: WorkbenchState | undefined
  workbenchState: WorkbenchState | undefined
  workbench_loading: boolean
  workbench_fetching: boolean
  workbench_error: unknown
  refetchWorkbench: () => Promise<QueryObserverResult<WorkbenchState, Error>>
  manual_filling_draft: ManualEditItem[]
  manual_filling_draft_scope: ManualFillingDraftScope | null
  manual_filling_preview: ManualFillingPreview | null
  beginManualFillingDraft: (scope: ManualFillingDraftScope) => void
  upsertManualFillingDraft: (item: ManualEditItem) => void
  setManualFillingPreview: (preview: ManualFillingPreview | null) => void
  removeManualFillingDraft: (objectRef: string) => void
  clearManualFillingDraft: () => void
  adoptBackendHead: (planVersionId: string, planningRevision: number) => void
  setMonth: (month: string) => void
}

const PlanningContext = createContext<PlanningContextValue | null>(null)

export function PlanningProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const formalReadOnly = isV6FormalReadOnlyPath(location.pathname)
  const [manualFillingDraft, setManualFillingDraft] = useState<ManualEditItem[]>([])
  const [manualFillingDraftScope, setManualFillingDraftScope] = useState<ManualFillingDraftScope | null>(null)
  const [manualFillingPreview, setManualFillingPreview] = useState<ManualFillingPreview | null>(null)
  const workbenchQuery = useQuery({
    queryKey: ['workbench-state'],
    queryFn: api.workbenchState,
    staleTime: 30_000,
    enabled: !formalReadOnly,
  })
  const planVersionId = workbenchQuery.data?.current_plan_version_id || null
  const annualQuery = useQuery({
    queryKey: ['annual-calendar', planVersionId],
    queryFn: () => api.annualCalendar(planVersionId as string),
    enabled: !formalReadOnly && Boolean(planVersionId),
    staleTime: 30_000,
  })
  const [month, setMonth] = useState<string | null>(null)
  const availableMonths = annualQuery.data?.months.map((item) => item.month) || []

  useEffect(() => {
    if (
      manualFillingDraftScope
      && (manualFillingDraftScope.plan_version_id !== planVersionId || manualFillingDraftScope.month !== month)
    ) {
      setManualFillingDraft([])
      setManualFillingDraftScope(null)
      setManualFillingPreview(null)
    }
  }, [manualFillingDraftScope, month, planVersionId])

  const beginManualFillingDraft = useCallback((scope: ManualFillingDraftScope) => {
    setManualFillingDraftScope((current) => {
      if (current?.plan_version_id === scope.plan_version_id && current.month === scope.month) return current
      setManualFillingDraft([])
      setManualFillingPreview(null)
      return scope
    })
  }, [])

  const upsertManualFillingDraft = useCallback((item: ManualEditItem) => {
    setManualFillingPreview(null)
    setManualFillingDraft((current) => [
      ...current.filter((entry) => entry.object_ref !== item.object_ref),
      item,
    ])
  }, [])

  const removeManualFillingDraft = useCallback((objectRef: string) => {
    setManualFillingDraft((current) => current.filter((entry) => entry.object_ref !== objectRef))
  }, [])

  const clearManualFillingDraft = useCallback(() => {
    setManualFillingDraft([])
    setManualFillingDraftScope(null)
    setManualFillingPreview(null)
  }, [])

  const adoptBackendHead = useCallback((planVersionId: string, planningRevision: number) => {
    queryClient.setQueryData<WorkbenchState>(['workbench-state'], (current) => (
      current
        ? { ...current, current_plan_version_id: planVersionId, planning_revision: planningRevision }
        : current
    ))
  }, [queryClient])

  const refetchWorkbench = useCallback(() => workbenchQuery.refetch(), [workbenchQuery.refetch])

  useEffect(() => {
    if (month === null && availableMonths.length > 0) setMonth(availableMonths[0])
    if (month !== null && availableMonths.length > 0 && !availableMonths.includes(month)) {
      setMonth(availableMonths[0])
    }
  }, [availableMonths, month])

  const value = useMemo<PlanningContextValue>(() => ({
    session_id: workbenchQuery.data?.session_id || null,
    planning_revision: workbenchQuery.data?.planning_revision ?? null,
    current_plan_version_id: planVersionId,
    factory: workbenchQuery.data?.factory_name || null,
    planning_year: workbenchQuery.data?.planning_year || (month ? Number(month.slice(0, 4)) : null),
    month,
    scenario: workbenchQuery.data?.scenario_display || null,
    available_months: availableMonths,
    workbench: workbenchQuery.data,
    workbenchState: workbenchQuery.data,
    workbench_loading: workbenchQuery.isLoading,
    workbench_fetching: workbenchQuery.isFetching,
    workbench_error: workbenchQuery.error,
    refetchWorkbench,
    manual_filling_draft: manualFillingDraft,
    manual_filling_draft_scope: manualFillingDraftScope,
    manual_filling_preview: manualFillingPreview,
    beginManualFillingDraft,
    upsertManualFillingDraft,
    setManualFillingPreview,
    removeManualFillingDraft,
    clearManualFillingDraft,
    adoptBackendHead,
    setMonth,
  }), [adoptBackendHead, availableMonths, beginManualFillingDraft, clearManualFillingDraft, manualFillingDraft, manualFillingDraftScope, manualFillingPreview, month, planVersionId, refetchWorkbench, removeManualFillingDraft, setManualFillingPreview, upsertManualFillingDraft, workbenchQuery.data, workbenchQuery.error, workbenchQuery.isFetching, workbenchQuery.isLoading])

  return <PlanningContext.Provider value={value}>{children}</PlanningContext.Provider>
}

export function usePlanning() {
  const value = useContext(PlanningContext)
  if (!value) throw new Error('usePlanning must be used within PlanningProvider')
  return value
}
