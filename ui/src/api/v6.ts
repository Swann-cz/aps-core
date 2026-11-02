import { ApiError, request, requestFile } from './client'
import type {
  V6ActualFillingApplyRequest,
  V6ActualFillingApplyResponse,
  V6ActualFillingErrorReportRequest,
  V6ActualFillingPreviewRequest,
  V6ActualFillingPreviewResponse,
  V6CommandResult,
  V6CandidateAnnualOverview,
  V6CandidateMonthlyFilling,
  V6ConditionDraft,
  V6ConditionOptionInventory,
  V6FormalCompareResponse,
  V6FormalAnnualOverview,
  V6FormalMonthlyFilling,
  V6FormalPPVersion,
  V6PRVersion,
  V6Session,
  V6SessionStartRequest,
  V6Workbench,
  V6WSVersion,
} from '../types/v6'
import type {
  ActualRevision,
  AlgorithmSlot,
  CalendarVersion,
  FactoryModelVersion,
  InitialStateSnapshot,
  InitialStateSnapshotDetail,
  WipTargetVersion,
  WipTargetVersionDetail,
} from '../types/api'

const API_BASE = import.meta.env.VITE_API_BASE_URL || '/api/v1'

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
})

function actualFillingImportForm(data: V6ActualFillingPreviewRequest): FormData {
  const form = new FormData()
  form.append('file', data.file)
  form.append('confirmed_effective_date', data.confirmedEffectiveDate)
  if (data.supersedesActualRevisionId) form.append('supersedes_actual_revision_id', data.supersedesActualRevisionId)
  if (data.reason) form.append('reason', data.reason)
  return form
}

async function requestMultipartFile(path: string, body: FormData): Promise<{ blob: Blob; filename: string }> {
  const response = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { Accept: '*/*' },
    body,
  })
  if (!response.ok) {
    let detail: unknown = response.statusText
    try {
      detail = await response.json()
    } catch {
      detail = response.statusText
    }
    throw new ApiError(response.status, detail)
  }
  const disposition = response.headers.get('Content-Disposition') || ''
  const filename = disposition.match(/filename="?([^";]+)"?/i)?.[1] || 'actual-filling-error-report.xlsx'
  return { blob: await response.blob(), filename }
}

export const v6Api = {
  conditionOptions: () => request<V6ConditionOptionInventory>('/v6/condition-options'),
  prVersions: () => request<V6PRVersion[]>('/pr-versions'),
  prVersion: (id: string) => request<V6PRVersion>(`/pr-versions/${encodeURIComponent(id)}`),
  wsVersions: () => request<V6WSVersion[]>('/ws-versions'),
  wsVersion: (id: string) => request<V6WSVersion>(`/ws-versions/${encodeURIComponent(id)}`),
  factoryVersions: () => request<(FactoryModelVersion & { business_id?: string })[]>('/factory-model-versions'),
  factoryVersion: (id: string) => request<Record<string, unknown>>(`/factory-model-versions/${encodeURIComponent(id)}`),
  calendarVersions: () => request<(CalendarVersion & { business_id?: string })[]>('/calendar-versions'),
  calendarVersion: (id: string) => request<Record<string, unknown>>(`/calendar-versions/${encodeURIComponent(id)}`),
  initialStateVersions: () => request<(InitialStateSnapshot & { business_id?: string })[]>('/initial-state-snapshots'),
  initialStateVersion: (id: string) => request<InitialStateSnapshotDetail & { business_id?: string }>(`/initial-state-snapshots/${encodeURIComponent(id)}`),
  wipPolicyVersions: () => request<(WipTargetVersion & { business_id?: string })[]>('/wip-target-versions'),
  wipPolicyVersion: (id: string) => request<WipTargetVersionDetail & { business_id?: string }>(`/wip-target-versions/${encodeURIComponent(id)}`),
  actualRevisions: () => request<(ActualRevision & { business_id?: string })[]>('/actual-revisions'),
  actualRevision: (id: string) => request<Record<string, unknown>>(`/actual-revisions/${encodeURIComponent(id)}`),
  algorithmOptions: (slot: string) => request<AlgorithmSlot[]>(`/algorithms/${encodeURIComponent(slot)}/options`),

  sessions: (status?: string) => request<V6Session[]>(`/v6/sessions${status ? `?status=${encodeURIComponent(status)}` : ''}`),
  session: (id: string) => request<V6Session>(`/v6/sessions/${encodeURIComponent(id)}`),
  workbench: (id: string, candidateId?: string | null) => request<V6Workbench>(
    `/v6/sessions/${encodeURIComponent(id)}/workbench${candidateId ? `?candidate_id=${encodeURIComponent(candidateId)}` : ''}`,
  ),
  startSession: (data: V6SessionStartRequest) => request<V6CommandResult>('/v6/sessions', json(data)),
  generateCandidate: (sessionId: string, expectedPlanningRevision: number) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/candidates`,
    json({ expected_planning_revision: expectedPlanningRevision }),
  ),
  candidate: (candidateId: string) => request<Record<string, unknown>>(`/v6/draft-candidates/${encodeURIComponent(candidateId)}`),
  candidateAnnualOverview: (candidateId: string) => request<V6CandidateAnnualOverview>(`/v6/draft-candidates/${encodeURIComponent(candidateId)}/annual-overview`),
  candidateMonthlyFilling: (candidateId: string, month: string) => request<V6CandidateMonthlyFilling>(`/v6/draft-candidates/${encodeURIComponent(candidateId)}/monthly-filling?month=${encodeURIComponent(month)}`),
  restoreCandidate: (sessionId: string, candidateId: string, expectedPlanningRevision: number) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/candidate-restores`,
    json({ target_candidate_id: candidateId, expected_planning_revision: expectedPlanningRevision }),
  ),
  recoverAbandonedDraft: (sessionId: string, candidateId: string) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/recoveries`,
    json({ target_candidate_id: candidateId }),
  ),
  abandonSession: (sessionId: string, expectedPlanningRevision: number) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/abandon`,
    json({ expected_planning_revision: expectedPlanningRevision }),
  ),
  replanHolidayWindows: (sessionId: string, candidateId: string, expectedPlanningRevision: number) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/holiday-window-replans`,
    json({ source_candidate_id: candidateId, expected_planning_revision: expectedPlanningRevision }),
  ),

  createManualDraft: (sessionId: string, proposalItems: Record<string, unknown>[]) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/condition-drafts`,
    json({ proposal_items: proposalItems }),
  ),
  mergeDrafts: (sessionId: string, drafts: { draft_id: string; expected_draft_revision: number }[]) => request<V6CommandResult>(
    `/v6/sessions/${encodeURIComponent(sessionId)}/condition-draft-merges`,
    json({ drafts }),
  ),
  interpretDraft: (sessionId: string, rawText: string) => request<V6CommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/interpret`,
    json({ raw_text: rawText }),
  ),
  conditionDraft: (sessionId: string, draftId: string) => request<V6ConditionDraft>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}`,
  ),
  patchDraft: (sessionId: string, draftId: string, expectedDraftRevision: number, proposalItems: Record<string, unknown>[]) => request<V6CommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}`,
    { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ expected_draft_revision: expectedDraftRevision, proposal_items: proposalItems }) },
  ),
  previewDraft: (sessionId: string, draftId: string, expectedDraftRevision: number) => request<V6CommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}/preview`,
    json({ expected_draft_revision: expectedDraftRevision }),
  ),
  draftPreview: (sessionId: string, draftId: string, draftRevision: number) => request<Record<string, unknown>>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}/preview?draft_revision=${draftRevision}`,
  ),
  approvalGrant: (sessionId: string, draftId: string, expectedDraftRevision: number) => request<V6CommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}/approval-grants`,
    json({ expected_draft_revision: expectedDraftRevision, ttl_seconds: 300 }),
  ),
  applyDraft: (sessionId: string, draftId: string, expectedDraftRevision: number, approvalToken: string) => request<V6CommandResult>(
    `/sessions/${encodeURIComponent(sessionId)}/condition-drafts/${encodeURIComponent(draftId)}/apply`,
    json({ expected_draft_revision: expectedDraftRevision, approval_token: approvalToken }),
  ),

  saveFormal: (
    sessionId: string,
    data: { expected_planning_revision: number; display_name: string; work_note: string; warning_acknowledgements: { warning_code: string; reason: string }[] },
  ) => request<V6CommandResult>(`/v6/sessions/${encodeURIComponent(sessionId)}/formal-pp-versions`, json({ ...data, saved_by: 'frontend-human' })),
  formalVersions: () => request<V6FormalPPVersion[]>('/v6/formal-pp-versions'),
  formalVersion: (id: string) => request<V6FormalPPVersion>(`/v6/formal-pp-versions/${encodeURIComponent(id)}`),
  formalAnnualOverview: (id: string) => request<V6FormalAnnualOverview>(`/v6/formal-pp-versions/${encodeURIComponent(id)}/annual-overview`),
  formalMonthlyFilling: (id: string, month: string) => request<V6FormalMonthlyFilling>(`/v6/formal-pp-versions/${encodeURIComponent(id)}/monthly-filling?month=${encodeURIComponent(month)}`),
  exportFormalMonthlyFilling: (id: string, month: string) => requestFile(
    `/v6/formal-pp-versions/${encodeURIComponent(id)}/monthly-filling/export?month=${encodeURIComponent(month)}&format=xlsx`,
  ),
  exportFormalAnnualFilling: (id: string, year: number) => requestFile(
    `/v6/formal-pp-versions/${encodeURIComponent(id)}/annual-filling/export?year=${encodeURIComponent(String(year))}&format=xlsx`,
  ),
  previewActualFillingImport: (data: V6ActualFillingPreviewRequest) => request<V6ActualFillingPreviewResponse>(
    '/v6/actual-filling-imports/preview',
    { method: 'POST', body: actualFillingImportForm(data) },
  ),
  applyActualFillingImport: (data: V6ActualFillingApplyRequest) => {
    const form = actualFillingImportForm({
      file: data.file,
      confirmedEffectiveDate: data.confirmedEffectiveDate,
      supersedesActualRevisionId: data.supersedesActualRevisionId,
    })
    form.append('expected_workbook_sha256', data.expectedWorkbookSha256)
    form.append('expected_preview_fingerprint', data.expectedPreviewFingerprint)
    form.append('reason', data.reason)
    form.append('idempotency_key', data.idempotencyKey)
    return request<V6ActualFillingApplyResponse>('/v6/actual-filling-imports/apply', { method: 'POST', body: form })
  },
  actualFillingImportApplication: (idempotencyKey: string) => request<V6ActualFillingApplyResponse>(
    `/v6/actual-filling-imports/applications/${encodeURIComponent(idempotencyKey)}`,
  ),
  downloadActualFillingErrorReport: (data: V6ActualFillingErrorReportRequest) => {
    const form = actualFillingImportForm(data)
    form.append('expected_workbook_sha256', data.expectedWorkbookSha256)
    form.append('expected_preview_fingerprint', data.expectedPreviewFingerprint)
    if (data.reason) form.append('reason', data.reason)
    return requestMultipartFile('/v6/actual-filling-imports/error-report', form)
  },
  compareFormal: (oldId: string, newId: string) => request<V6FormalCompareResponse>('/v6/formal-pp-versions/compare', json({ formal_pp_ids: [oldId, newId] })),
}
