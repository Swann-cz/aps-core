export type ScenarioSummary = {
  id: string; name: string; created_at: string
  state: 'NO_PLAN' | 'RUNNING' | 'FAILED' | 'STALE' | 'READY'
  run: { state: 'IDLE' | 'RUNNING' | 'FAILED'; started_at: string | null; finished_at: string | null; seconds: number | null; error: string | null; warm_start?: boolean; kept_previous?: boolean }
  plan_status: string | null; verdict: string | null; hard_error_count: number
  no_plan: boolean; findings: unknown[]
  solver?: { name: string; seconds: number } | null
  objective: Record<string, number> | null
  formal: { source_id: string; confirmed_at: string; note: string } | null
}
export type ConditionType = 'SATURDAY_AUTH' | 'MODE_AUTH' | 'SHUTDOWN' | 'CAPACITY_LOSS' | 'WIP_TARGET' | 'PRE_STOP_TARGET' | 'FIXED_OUTPUT'
export type Condition = {
  id: string; type: ConditionType; reason?: string; date?: string; start?: string; end?: string
  workshops?: string[]; workshop?: string; node?: string; mode?: string
  hours_max?: number; target?: number; out?: number; pre_stop_date?: string
}
export type ConditionsView = {
  scenario: ScenarioSummary; conditions: Condition[]
  options: { caps: Record<string, number | null>; horizon: { start: string; end: string }; workshops: string[]; nodes: string[]; auth_modes: string[] }
}
export type SuggestObjective = { L1a: number; L1b: number; L1c: number; L3a: number; L3b: number }
export type SuggestView = {
  stage: 'NEED_RUN' | 'NO_GAP' | 'HAS_GAP' | 'EXHAUSTED' | 'CANDIDATES_PENDING' | 'CANDIDATES_DONE'
  next_mode: string | null
  gaps: { month: string; model: string; cum_gap: number; band_short: number }[]
  candidates: { saturdays: string[]; overtime: { id: string; mode: string; start: string; end: string }[] }
  usage: null | {
    saturdays_used: string[]; saturdays_unused: string[]
    overtime_used: { id: string; mode: string; days: { date: string; workshops: string[] }[] }[]
    overtime_unused_ids: string[]
  }
  baseline: SuggestObjective | null; current: SuggestObjective | null
}
export type DayCondition = Pick<Condition, 'id' | 'type'>
export type AnnualDay = { date: string; is_working_capable: boolean; fok: number; mode_summary: string; phase: string; conditions: DayCondition[] }
export type AnnualMonth = {
  month: string; pr: number; fok: number; ws: number; cum_gap: number; band_short: number; fin_eom: number
  wip_eom: Record<string, number>; weld_days: Record<string, number>; saturday_days: number; overtime_days: number; phases: string[]
}
export type AnnualView = {
  scenario: ScenarioSummary; caps: Record<string, number | null>; horizon: { start: string; end: string }
  totals: { annual_pr: number; annual_fok: number; annual_gap: number; production_days: number; saturday_days: number; overtime_days: number }
  models: { model: string; annual_pr: number; annual_fok: number; annual_gap: number; months: Record<string, { pr: number; fok: number; cum_gap: number; band_short: number }> }[]
  months: AnnualMonth[]; days: AnnualDay[]
  stop_list: { start: string; end: string; length: number; pre_stop_date: string | null; target: number | null; source: string }[]
  findings: unknown[]; hard_errors: { rule: string; date: string | null; node: string | null; model: string | null; detail: string }[]
}
export type Flow = { bod: number; in: number; out: number; eod: number }
export type MonthlyDay = {
  date: string; is_working_capable: boolean; phase: string; conditions: DayCondition[]
  mode_summary: string; hours_max: number
  workshops: Record<string, Flow & { mode: string; hours: number; jph: number; in_cum: number; out_cum: number; by_model: Record<string, Flow> }>
  buffers: Record<string, Flow & { by_model: Record<string, Flow> }>
  fin: { fok: number; fok_cum: number; ws: number; ws_cum: number; eod: number; bl: number; by_model: Record<string, { fok: number; ws: number; eod: number; bl: number }> }
}
export type MonthlyView = { scenario: ScenarioSummary; month: string; models: string[]; targets: Record<string, number>; caps: Record<string, number | null>; days: MonthlyDay[] }
async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api${path}`, { method, ...(body === undefined ? {} : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail)
  return data
}
const scenarioPath = (id: string) => `/scenarios/${encodeURIComponent(id)}`
export type ImportError = { file: string; row: number | null; message: string }
export type PlanPreview = {
  ok: boolean; errors: ImportError[]
  summary: { models: Record<string, { pr: number; ws: number; initial_wip: number }>; working_days: number; fin0: Record<string, number> }
}
export type FullImportError = { sheet: string; row: number | null; column: string | null; message: string }
export type FullPlanPreview = Omit<PlanPreview, 'errors'> & { errors: FullImportError[] }
export class FullPlanImportError extends Error {
  constructor(message: string, public errors: FullImportError[]) { super(message) }
}
async function uploadFullPlan<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`/api${path}`, { method: 'POST', body })
  const data = await response.json()
  if (!response.ok) throw new FullPlanImportError(data.detail, data.errors ?? [])
  return data
}
export class PlanImportError extends Error {
  constructor(message: string, public errors: ImportError[]) { super(message) }
}
async function uploadPlan<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`/api${path}`, { method: 'POST', body })
  const data = await response.json()
  if (!response.ok) throw new PlanImportError(data.detail, data.errors ?? [])
  return data
}
export const core = {
  previewFullPlan: (body: FormData) => uploadFullPlan<FullPlanPreview>('/import/preview', body),
  createFullPlan: (body: FormData) => uploadFullPlan<ScenarioSummary>('/import', body),
  previewPlan: (body: FormData) => uploadPlan<PlanPreview>('/new-plan/preview', body),
  createPlan: (body: FormData) => uploadPlan<ScenarioSummary>('/new-plan', body),
  finalize: (id: string, note: string) => request<ScenarioSummary>(`${scenarioPath(id)}/finalize`, 'POST', { note }),
  template: async (kind: string, baseId: string | undefined, year: string) => {
    const response = await fetch(`/api/templates/${kind}?${new URLSearchParams({ ...(baseId ? { base_id: baseId } : {}), year })}`)
    if (!response.ok) throw new Error((await response.json()).detail)
    return response.blob()
  },
  scenarios: () => request<ScenarioSummary[]>('/scenarios'),
  copy: (from_id: string, name: string) => request<ScenarioSummary>('/scenarios', 'POST', { from_id, name }),
  run: (id: string) => request<ScenarioSummary>(`${scenarioPath(id)}/run`, 'POST'),
  conditions: (id: string) => request<ConditionsView>(`${scenarioPath(id)}/conditions`),
  suggest: (id: string) => request<SuggestView>(`${scenarioPath(id)}/suggest`),
  suggestCandidates: (id: string) => request<SuggestView>(`${scenarioPath(id)}/suggest/candidates`, 'POST'),
  suggestApply: (id: string) => request<SuggestView>(`${scenarioPath(id)}/suggest/apply`, 'POST'),
  suggestDiscard: (id: string) => request<SuggestView>(`${scenarioPath(id)}/suggest/discard`, 'POST'),
  saveConditions: (id: string, conditions: Condition[]) => request<ScenarioSummary>(`${scenarioPath(id)}/conditions`, 'PUT', { conditions }),
  annual: (id: string) => request<AnnualView>(`${scenarioPath(id)}/annual`),
  monthly: (id: string, month: string) => request<MonthlyView>(`${scenarioPath(id)}/monthly?month=${encodeURIComponent(month)}`),
}
export const conditionNames: Record<ConditionType, string> = { SATURDAY_AUTH: '周六授权', MODE_AUTH: '加班模式授权', SHUTDOWN: '计划停线', CAPACITY_LOSS: '产能损失', WIP_TARGET: '人工目标在制', PRE_STOP_TARGET: '人工停前目标', FIXED_OUTPUT: '指定产量' }
const phases: Record<string, string> = { NORMAL: '正常', PS_PRE_STOP: '停前降库', STOP: '停线', BS_CLEAR: '焊装清线', REFILL: '复线补库', FIRST_START: '首次启动', CHANGEOVER: '换型', MODEL_EXIT: '车型退出', INITIAL_DRAIN: '期初排空' }
export const phaseName = (phase: string) => phase.split('+').map(item => phases[item] ?? item).join('、')
export const modeName = (mode: string) => ({ OFF: '停', SINGLE_8H: '单班 8h', SINGLE_8P2: '单班 8+2h', SINGLE_8P3: '单班 8+3h', DOUBLE_SHIFT: '双班' }[mode] ?? mode)
export const planStatusName = (status: string) => ({ FEASIBLE: '可行', UNKNOWN: '尚未确定', PROVEN_INFEASIBLE: '已证明不可行', INPUT_INVALID: '输入无效', EXECUTION_ERROR: '执行错误' }[status] ?? status)
export const quantity = (value: number) => value.toLocaleString('zh-CN', { maximumFractionDigits: 0 })
export const findingText = (finding: unknown) => typeof finding === 'string' ? finding : JSON.stringify(finding)

export const capText = (cap: number | null) => cap === null ? '上限 = 目标' : `上限 ${quantity(cap)}`
