import { request, requestFile } from './client'
import type {
  ActiveCondition,
  AnnualCalendar,
  ChoiceTree,
  DailyEffectiveStatus,
  Explanation,
  MonthlyFilling,
  PlanComparison,
  PlanHealth,
  PlanHistory,
  AlgorithmProfile,
  AlgorithmSlot,
  ConfirmationGate,
  ManualEditItem,
  PlanningCommandResult,
  WorkbenchState,
  SalesPlanVersion,
  FactoryModelVersion,
  CalendarVersion,
  ActualRevision,
  InitialStateSnapshot,
  InitialStateSnapshotDetail,
  PreflightResult,
  StartSessionRequest,
  GeneratePlanRequest,
  PlanningIssue,
  WipTargetVersion,
  WipTargetVersionDetail,
  WipTargetCreateRequest,
} from '../types/api'

function actionRequest(
  sessionId: string,
  endpoint: 'preview' | 'apply',
  expectedPlanningRevision: number,
  actionType: string,
  payload: Record<string, unknown>,
) {
  return request<PlanningCommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/actions/${endpoint}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        expected_planning_revision: expectedPlanningRevision,
        action_type: actionType,
        payload,
      }),
    },
  )
}

export const api = {
  workbenchState: () => request<WorkbenchState>('/workbench/state'),
  annualCalendar: (planVersionId: string) =>
    request<AnnualCalendar>(`/plans/${encodeURIComponent(planVersionId)}/annual-calendar`),
  monthlyFilling: (planVersionId: string, month: string) =>
    request<MonthlyFilling>(
      `/plans/${encodeURIComponent(planVersionId)}/months/${encodeURIComponent(month)}/filling`,
    ),
  // Phase 3A: single daily effective-status projection (Calendar/Agent/UI)
  dailyStatus: (planVersionId: string, startDate?: string, endDate?: string) => {
    const params = new URLSearchParams()
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    const qs = params.toString()
    return request<DailyEffectiveStatus[]>(
      `/plans/${encodeURIComponent(planVersionId)}/daily-status${qs ? `?${qs}` : ''}`,
    )
  },
  explanation: (planVersionId: string, objectRef: string) =>
    request<Explanation>(
      `/plans/${encodeURIComponent(planVersionId)}/explanations?object_ref=${encodeURIComponent(objectRef)}`,
    ),
  getIssues: (planVersionId: string) =>
    request<PlanningIssue[]>(`/plans/${encodeURIComponent(planVersionId)}/issues`),
  // Epic 0: Active Conditions Query (V4 UI Final freeze)
  getActiveConditions: (planVersionId: string) =>
    request<ActiveCondition[]>(`/plans/${encodeURIComponent(planVersionId)}/conditions`),
  planHealth: (planVersionId: string) =>
    request<PlanHealth>(`/plans/${encodeURIComponent(planVersionId)}/health`),
  confirmationGate: (planVersionId: string) =>
    request<ConfirmationGate>(`/plans/${encodeURIComponent(planVersionId)}/confirmation-gate`),
  previewAction: (
    sessionId: string,
    expectedPlanningRevision: number,
    actionType: string,
    payload: Record<string, unknown>,
  ) => actionRequest(sessionId, 'preview', expectedPlanningRevision, actionType, payload),
  applyAction: (
    sessionId: string,
    expectedPlanningRevision: number,
    actionType: string,
    payload: Record<string, unknown>,
  ) => actionRequest(sessionId, 'apply', expectedPlanningRevision, actionType, payload),
  // Phase 2: server-side Condition Builder owns business translation/defaults.
  buildCondition: (data: {
    plan_version_id?: string
    action_type?: string
    capability_id?: string
    intent_type?: string
    params: Record<string, unknown>
  }) =>
    request<{
      action_type?: string
      capability_id?: string
      intent_type?: string
      payload: Record<string, unknown>
      planning_conditions?: Record<string, unknown>[]
    }>(
      '/conditions/build',
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      },
    ),
  confirmPlan: (sessionId: string, planVersionId: string, expectedPlanningRevision: number) =>
    request<PlanningCommandResult>(
      `/sessions/${encodeURIComponent(sessionId)}/confirmations`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_planning_revision: expectedPlanningRevision,
          plan_version_id: planVersionId,
        }),
      },
    ),
  rollForwardActual: (sessionId: string, expectedPlanningRevision: number, actualRevisionId: string) =>
    request<PlanningCommandResult>(
      `/sessions/${encodeURIComponent(sessionId)}/roll-forward-actual`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_planning_revision: expectedPlanningRevision,
          actual_revision_id: actualRevisionId,
        }),
      },
    ),
  adoptSales: (sessionId: string, expectedPlanningRevision: number, salesPlanVersionId: string) =>
    request<PlanningCommandResult>(
      `/sessions/${encodeURIComponent(sessionId)}/adopt-sales`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_planning_revision: expectedPlanningRevision,
          sales_plan_version_id: salesPlanVersionId,
        }),
      },
    ),
  planHistory: (sessionId: string) =>
    request<PlanHistory[]>(`/sessions/${encodeURIComponent(sessionId)}/plan-history`),
  // Epic C: Choice Tree (renderer input; backend-owned tree model)
  choiceTree: (sessionId: string) =>
    request<ChoiceTree>(`/sessions/${encodeURIComponent(sessionId)}/choice-tree`),
  algorithmProfile: (planVersionId: string) =>
    request<AlgorithmProfile>(`/plans/${encodeURIComponent(planVersionId)}/algorithm-profile`),
  getAlgorithmOptions: (slot: string) =>
    request<AlgorithmSlot[]>(`/algorithms/${encodeURIComponent(slot)}/options`),
  changeAlgorithmProfile: (
    sessionId: string,
    expectedPlanningRevision: number,
    algorithmProfile: Record<string, AlgorithmSlot>,
  ) =>
    request<PlanningCommandResult>(
      `/sessions/${encodeURIComponent(sessionId)}/algorithm-profile`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_planning_revision: expectedPlanningRevision,
          algorithm_profile: algorithmProfile,
        }),
      },
    ),
  comparePlans: (leftPlanVersionId: string, rightPlanVersionId: string) =>
    request<PlanComparison>(
      `/plans/compare?left_plan_version_id=${encodeURIComponent(leftPlanVersionId)}&right_plan_version_id=${encodeURIComponent(rightPlanVersionId)}`,
    ),
  exportFilling: (planVersionId: string, month: string, format: 'csv' | 'xlsx') =>
    requestFile(
      `/plans/${encodeURIComponent(planVersionId)}/months/${encodeURIComponent(month)}/filling/export?format=${format}`,
    ),

  // P00 Setup endpoints (Phase A/B)

  // Version list endpoints
  salesPlanVersions: () => request<SalesPlanVersion[]>('/sales-plan-versions'),
  factoryModelVersions: () => request<FactoryModelVersion[]>('/factory-model-versions'),
  calendarVersions: () => request<CalendarVersion[]>('/calendar-versions'),
  actualRevisions: () => request<ActualRevision[]>('/actual-revisions'),
  initialStateSnapshots: () => request<InitialStateSnapshot[]>('/initial-state-snapshots'),
  initialStateSnapshotDetail: (snapshotId: string) =>
    request<InitialStateSnapshotDetail>(`/initial-state-snapshots/${encodeURIComponent(snapshotId)}`),

  // Input version details (P3: edit must reflect existing content)
  salesPlanVersionDetail: (versionId: string) =>
    request<any>(`/sales-plan-versions/${encodeURIComponent(versionId)}`),
  factoryModelVersionDetail: (versionId: string) =>
    request<any>(`/factory-model-versions/${encodeURIComponent(versionId)}`),
  calendarVersionDetail: (versionId: string) =>
    request<any>(`/calendar-versions/${encodeURIComponent(versionId)}`),
  actualRevisionDetail: (revisionId: string) =>
    request<any>(`/actual-revisions/${encodeURIComponent(revisionId)}`),

  // Version creation endpoints
  createSalesPlanVersion: (data: { display_name: string; months: any[]; source?: string; supersedes_sales_plan_version_id?: string }) =>
    request<PlanningCommandResult>('/sales-plan-versions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  createFactoryModelVersion: (data: { display_name: string; factory_model: any; supersedes_factory_model_version_id?: string }) =>
    request<PlanningCommandResult>('/factory-model-versions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  createCalendarVersion: (data: { display_name: string; days: any[]; supersedes_calendar_version_id?: string }) =>
    request<PlanningCommandResult>('/calendar-versions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  createActualRevision: (data: { effective_date: string; entries: any[]; reason?: string; supersedes_revision_id?: string; actor?: string }) =>
    request<PlanningCommandResult>('/actual-revisions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  createInitialStateSnapshot: (data: { display_name: string; initial_state: any; supersedes_initial_state_snapshot_id?: string }) =>
    request<PlanningCommandResult>('/initial-state-snapshots', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Re-activate a historical version as the single current ACTIVE version
  activateSalesPlanVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/sales-plan-versions/${encodeURIComponent(versionId)}/activate`, { method: 'POST' }),
  activateFactoryModelVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/factory-model-versions/${encodeURIComponent(versionId)}/activate`, { method: 'POST' }),
  activateCalendarVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/calendar-versions/${encodeURIComponent(versionId)}/activate`, { method: 'POST' }),
  activateInitialStateSnapshot: (snapshotId: string) =>
    request<PlanningCommandResult>(`/initial-state-snapshots/${encodeURIComponent(snapshotId)}/activate`, { method: 'POST' }),
  archiveFactoryModelVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/factory-model-versions/${encodeURIComponent(versionId)}/archive`, { method: 'POST' }),
  archiveCalendarVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/calendar-versions/${encodeURIComponent(versionId)}/archive`, { method: 'POST' }),
  archiveInitialStateSnapshot: (snapshotId: string) =>
    request<PlanningCommandResult>(`/initial-state-snapshots/${encodeURIComponent(snapshotId)}/archive`, { method: 'POST' }),

  // Excel import endpoints
  importSalesPlan: (file: File, displayName?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (displayName) formData.append('display_name', displayName)
    return request<PlanningCommandResult>('/sales-plan-versions/import', {
      method: 'POST',
      body: formData,
    })
  },
  importFactoryModel: (file: File, displayName?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (displayName) formData.append('display_name', displayName)
    return request<PlanningCommandResult>('/factory-model-versions/import', {
      method: 'POST',
      body: formData,
    })
  },
  importCalendar: (file: File, displayName?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (displayName) formData.append('display_name', displayName)
    return request<PlanningCommandResult>('/calendar-versions/import', {
      method: 'POST',
      body: formData,
    })
  },
  importActualRevision: (file: File, effectiveDate: string, reason?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('effective_date', effectiveDate)
    if (reason) formData.append('reason', reason)
    return request<PlanningCommandResult>('/actual-revisions/import', {
      method: 'POST',
      body: formData,
    })
  },
  importInitialState: (file: File, displayName?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    if (displayName) formData.append('display_name', displayName)
    return request<PlanningCommandResult>('/initial-state-snapshots/import', {
      method: 'POST',
      body: formData,
    })
  },

  // Template download endpoints
  downloadSalesPlanTemplate: (calendarVersionId: string, factoryModelVersionId: string) => {
    const params = new URLSearchParams({
      calendar_version_id: calendarVersionId,
      factory_model_version_id: factoryModelVersionId,
    })
    return requestFile(`/import-templates/sales-plan?${params.toString()}`)
  },
  downloadFactoryModelTemplate: () => requestFile('/import-templates/factory-model'),
  downloadCalendarTemplate: () => requestFile('/import-templates/calendar'),
  downloadActualTemplate: () => requestFile('/import-templates/actual'),
  downloadInitialStateTemplate: () => requestFile('/import-templates/initial-state'),

  // Preflight endpoint
  preflight: (data: StartSessionRequest) =>
    request<PreflightResult>('/preflight', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Start Session endpoint
  startSession: (data: StartSessionRequest) =>
    request<PlanningCommandResult>('/sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // Generate Plan endpoint
  generatePlan: (sessionId: string, data: GeneratePlanRequest) =>
    request<PlanningCommandResult>(`/sessions/${encodeURIComponent(sessionId)}/generate-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),

  // V5 WIP Target versioned soft input (spec §10)
  wipTargetVersions: () => request<WipTargetVersion[]>('/wip-target-versions'),
  wipTargetVersionDetail: (versionId: string) =>
    request<WipTargetVersionDetail>(`/wip-target-versions/${encodeURIComponent(versionId)}`),
  createWipTargetVersion: (data: WipTargetCreateRequest) =>
    request<PlanningCommandResult>('/wip-target-versions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
  activateWipTargetVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/wip-target-versions/${encodeURIComponent(versionId)}/activate`, {
      method: 'POST',
    }),
  archiveWipTargetVersion: (versionId: string) =>
    request<PlanningCommandResult>(`/wip-target-versions/${encodeURIComponent(versionId)}/archive`, {
      method: 'POST',
    }),

  // V5 session Work Note (editable metadata, never plan truth/evidence)
  updateSessionWorkNote: (sessionId: string, workNote: string) =>
    request<PlanningCommandResult>(`/sessions/${encodeURIComponent(sessionId)}/work-note`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ work_note: workNote }),
    }),
}
