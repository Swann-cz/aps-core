export type ScalarValue = string | number | boolean | null

export interface WorkbenchState {
  session_id: string | null
  planning_revision: number
  current_plan_version_id: string | null
  status: string
  plan_status: string | null
  // Epic 0: dual planning status axes (V4 UI Final freeze).
  // version_status = PlanVersion workflow lifecycle (PROPOSED/CONFIRMED/...)
  // planner_state = backend-derived decision state (READY/ATTENTION/
  // DECISION_REQUIRED/BLOCKED); null outside an OPEN session with a
  // PROPOSED formal head. `plan_status` stays only for compatibility.
  version_status: string | null
  planner_state: string | null
  // V1.1 display context fields (GAP-UI-001 / GAP-UI-006 closure)
  factory_name: string | null
  planning_year: number | null
  scenario_display: string | null
  plan_display: string | null
  sales_display: string | null
  // V5 session metadata (editable Work Note + Confirmed Base lineage)
  base_confirmed_plan_version_id: string | null
  work_note: string | null
  work_note_updated_at: string | null
  work_note_updated_by: string | null
  // V5: open issue count (session-level OPEN scope, same as /plans/{id}/issues)
  outstanding_issue_count: number
}

export interface AlgorithmSlot {
  algorithm_id: string
  version: string
  display_name: string
}

export interface AlgorithmProfile {
  profile_id: string
  profile_version: string
  inventory_policy: AlgorithmSlot
  monthly_pp_allocation: AlgorithmSlot
  working_mode_selection: AlgorithmSlot
  block_placement: AlgorithmSlot
  welding_sequence: AlgorithmSlot
  candidate_selection: AlgorithmSlot
}

export interface AnnualDay {
  date: string
  calendar_state: string
  lock_state: string
  lock_source: string | null
  production_block_ref: string | null
  working_mode_summary: string | null
  // V5 fact: total planned units that day (backend-derived).
  planned_units: number
}

export interface MetricValue {
  metric_id: string
  display_name: string
  value: ScalarValue
  unit: string | null
}

export interface TypeclassMetric {
  typeclass_id: string
  metrics: MetricValue[]
}

export interface AnnualMonth {
  month: string
  pr_total: ScalarValue
  pp_target: ScalarValue
  pp_realized: ScalarValue
  ws_total: ScalarValue
  inventory_eom: ScalarValue
  pr_balance: ScalarValue
  capacity_headroom: ScalarValue
  plan_health: string
  issue_count: number
  working_mode_summary: string
  block_count: number
  locked_ratio: ScalarValue
  typeclass_metrics: TypeclassMetric[]
  days: AnnualDay[]
}

export interface AnnualCalendar {
  plan_version_id: string
  status: string
  sales_plan_version_id: string
  algorithm_profile: AlgorithmProfile
  months: AnnualMonth[]
  // V5 annual fact summary (backend-owned; UI renders, never computes).
  wip_target_deviation: ScalarValue
  double_shift_production_days: number
  annual_pp_total: ScalarValue
  annual_pr_total: ScalarValue
  annual_closure_gap: ScalarValue
  production_day_count: number
  days: AnnualDay[]
}

export interface DailyCalendarStatus {
  day_type: string
  is_holiday: boolean
}

export interface DailyProductionStatus {
  mode: string
  working_hours: number
  shift_count: number
  production_allowed: boolean
}

export interface DailySpecialEffect {
  type: string
  reason: string | null
}

export type EffectEvidenceStatus = 'EVALUATED' | 'NOT_EVALUATED'
export type PlanningEffectNodeId = 'BS1' | 'BS2' | 'WBS' | 'PS' | 'PBS' | 'AS' | 'AS_MAINLINE' | 'AS_FINISH_LINE' | 'FINISHED'
export type PlanningEffectNodeKind = 'WORKSHOP' | 'BUFFER' | 'INVENTORY'
export type PlanningEffectPhase = 'PRE_STOP' | 'STOP' | 'POST_STOP' | 'NORMAL'

export type NodeFlowRole = 'WBS' | 'PS' | 'PBS' | 'MAINLINE' | 'FINISH'

export interface TypeclassNodeFlow {
  typeclass_id: string
  bod: ScalarValue
  in: ScalarValue
  out: ScalarValue
  eod: ScalarValue
}

export interface MonthlyNodeFlow {
  role: NodeFlowRole
  node_id: 'WBS' | 'PS' | 'PBS' | 'AS_MAINLINE' | 'AS_FINISH_LINE'
  bod: ScalarValue
  in: ScalarValue
  out: ScalarValue
  eod: ScalarValue
  typeclass_flows: TypeclassNodeFlow[]
}

export interface PlanningDayEffect extends DailySpecialEffect {
  event_id: string
  node_kind: PlanningEffectNodeKind
  node_id: PlanningEffectNodeId
  typeclass_id: string
  quantity_scope?: 'TYPECLASS' | 'NODE_TOTAL'
  window_id: string | null
  phase: PlanningEffectPhase
  planned_in: number
  planned_out: number
  wip_bod: number | null
  wip_target: number | null
  wip_eod: number | null
  source_condition_ids: string[]
}

export type PlanningDayEffectsByNode = Partial<Record<PlanningEffectNodeId, PlanningDayEffect[]>>

export interface DailyOutputStatus {
  planned_units: number
  by_typeclass: Record<string, number>
}

export interface DailyEffectiveStatus {
  date: string
  calendar_status: DailyCalendarStatus
  production_status: DailyProductionStatus
  special_effects: DailySpecialEffect[]
  output: DailyOutputStatus
  source_plan_version_id: string
}

export interface FieldReference {
  field_name: string
  object_ref: string
  editable: boolean
  action_type: string | null
  edit_value_field: string | null
  edit_value_type: string | null
  edit_payload: Record<string, ScalarValue>
  lock_state: string
  lock_source: string | null
}

export interface AccumulateMetric {
  metric_id: string
  display_name: string
  value: ScalarValue
  unit: string | null
  typeclass_id: string | null
}

export interface WorkshopOutputQuantity {
  typeclass_id: string
  quantity: number
}

export interface WorkshopOutputFact {
  workshop_id: string
  working_mode_id: string
  out_by_typeclass: WorkshopOutputQuantity[]
}

export interface MonthlyDay {
  date: string
  calendar_state: string
  lock_state: string
  lock_source: string | null
  explanation_ref: string | null
  bs1_in: ScalarValue
  bs1_out: ScalarValue
  bs2_in: ScalarValue
  bs2_out: ScalarValue
  wbs_in: ScalarValue
  wbs_out: ScalarValue
  wbs_eod: ScalarValue
  ps_in: ScalarValue
  ps_out: ScalarValue
  pbs_in: ScalarValue
  pbs_out: ScalarValue
  pbs_eod: ScalarValue
  as_in: ScalarValue
  as_out: ScalarValue
  finished_inventory_eod: ScalarValue
  // V6 dual-AS projection. V5 keeps this as an empty array and continues to
  // use the historical flat AS fields above.
  node_flows: MonthlyNodeFlow[]
  // V1.2 (filling-system template display): workshop WIP EOD, per-station
  // cumulative flows and finished-line output (backend-computed).
  bs1_eod: ScalarValue
  bs2_eod: ScalarValue
  ps_eod: ScalarValue
  as_eod: ScalarValue
  bs1_in_cumulative: ScalarValue
  bs1_out_cumulative: ScalarValue
  bs2_in_cumulative: ScalarValue
  bs2_out_cumulative: ScalarValue
  wbs_in_cumulative: ScalarValue
  wbs_out_cumulative: ScalarValue
  ps_in_cumulative: ScalarValue
  ps_out_cumulative: ScalarValue
  pbs_in_cumulative: ScalarValue
  pbs_out_cumulative: ScalarValue
  as_in_cumulative: ScalarValue
  as_out_cumulative: ScalarValue
  finished_output: ScalarValue
  finished_output_cumulative: ScalarValue
  working_mode: string | null
  jph: ScalarValue
  hours: ScalarValue
  production_block_ref: string | null
  typeclass_metrics: TypeclassMetric[]
  accumulate_metrics: AccumulateMetric[]
  workshop_output_facts: WorkshopOutputFact[]
  applied_effect_refs: string[]
  field_refs: FieldReference[]
  // V1.1: backend-authoritative planning_state (GAP-UI-002 closure)
  planning_state: string
  // CLEARING v2 markers: day inside an auto/manual line-clear window, or the
  // restart day right after a shutdown (welding / WBS columns get colors).
  clearing_day: boolean
  restart_day: boolean
  shutdown_day?: boolean
  special_effects?: DailySpecialEffect[]
  effects_by_node?: PlanningDayEffectsByNode
  condition_result_refs?: string[]
}

export interface ActionView {
  action_type: string
  display_name: string
  requires_human_confirmation: boolean
  preview_supported: boolean
  parameters_schema: Record<string, unknown>
  impact_kind: string | null
  impact_summary: string | null
  affected_scope: string[]
}

export interface PlanningIssue {
  issue_id: string
  issue_type: string
  severity: string
  status: string // OPEN / RESOLVED（后端派生，F5）
  scope: string[]
  what_happened: string
  why: string
  blocking_boundary: string
  gap: ScalarValue
  available_actions: ActionView[]
  evidence_refs: string[]
  affected_objects: string[]
  system_tried: string[]
}

export interface MonthlyFilling {
  plan_version_id: string
  month: string
  days: MonthlyDay[]
  summary: { metrics: MetricValue[] }
  issues: PlanningIssue[]
}

export interface RejectedCandidate {
  candidate_value: string
  reason: string
}

export interface Explanation {
  object_ref: string
  headline: string
  decision: string
  reason_chain: string[]
  hard_constraints: string[]
  business_intents: string[]
  applied_effects: string[]
  algorithm_provenance: string[]
  evidence_refs: string[]
  rejected_candidates: RejectedCandidate[]
}

export interface PlanHealth {
  plan_health: string
  hard_validation: string | null
  outstanding_issue_count: number
}

export interface ConfirmationGate {
  plan_version_id: string
  can_confirm: boolean
  hard_validation: string | null
  hard_valid: boolean
  blocking_issue_count: number
  blocking_reasons: string[]
  algorithm_profile_valid: boolean
  input_version_consistent: boolean
}

export interface ManualEditItem {
  object_ref: string
  action_type: string
  payload: Record<string, ScalarValue>
  lock_after_apply?: boolean
}

export interface ManualFillingDraftScope {
  plan_version_id: string
  month: string
}

export interface ManualFillingPreview {
  base_plan_version_id: string
  what_if_plan_version_id: string
  planning_revision: number
  month: string
}

export interface PlanningCommandResult {
  ok: boolean
  outcome_type: string
  outcome: string
  message: string
  session_id?: string
  planning_revision?: number
  plan_version_id?: string
  actual_revision_id?: string
  what_if_plan_version_id?: string
  payload?: Record<string, unknown>
  issues?: PlanningIssue[]
  actual_locked_through?: string | null
  mutable_replan_start?: string | null
  mutable_dates?: string[]
  protected_dates?: ActualProtectedDateRange[]
  explicit_locked_dates?: string[]
}

export interface HistoryEvent {
  event_type: string
  display_name: string
  occurred_at: string | null
  object_ref: string | null
  evidence_refs: string[]
}

export interface PlanHistory {
  plan_version_id: string
  parent_plan_version_id: string | null
  status: string
  created_at: string
  confirmed_at: string | null
  sales_plan_version_id: string
  algorithm_profile: AlgorithmProfile
  actions: HistoryEvent[]
  decision_events: HistoryEvent[]
  session_id: string | null
  display_name: string | null
  presentation_role: string | null
  branch_label: string | null
  base_confirmed_plan_version_id: string | null
}

// Epic C: backend-owned choice tree model (never a frontend-invented tree).
export interface ChoiceTreeNode {
  version_id: string
  display_sequence: number
  role: string
  status: string
  parent_version_id: string | null
  base_confirmed_version_id: string | null
  confirmed: boolean
}

export interface ChoiceTreeEdge {
  comparison_id: string
  left: string
  right: string
  outcome: string | null
  selected: string | null
  summary: string
}

export interface ChoiceTree {
  session_id: string
  nodes: ChoiceTreeNode[]
  comparison_edges: ChoiceTreeEdge[]
}

export interface DiffEntry {
  object_ref: string
  metric_id: string
  display_name: string
  left_value: ScalarValue
  right_value: ScalarValue
  delta: ScalarValue
  change_type: string
  category: string
}

export interface IntentDiff {
  intent_id: string
  metric: string | null
  priority_tier: number | null
  left_status: string | null
  right_status: string | null
}

export interface PlanComparison {
  left_plan_version_id: string
  right_plan_version_id: string
  summary_diff: DiffEntry[]
  monthly_diff: DiffEntry[]
  metric_diff: DiffEntry[]
  issue_diff: DiffEntry[]
  changed_blocks: DiffEntry[]
  changed_days: DiffEntry[]
  policy_diff: DiffEntry[]
  // Epic 0: semantic compare additions (V4 UI Final freeze)
  intent_diff: IntentDiff[]
  summary: string
  // V5 backend-owned verdict (spec §18.12)
  core_metrics: ComparisonMetric[]
  verdict_summary: string
  advantages: ComparisonMetric[]
  disadvantages: ComparisonMetric[]
  key_differences: ComparisonMetric[]
}

export interface ComparisonMetric {
  metric_id: string
  label: string
  left_value: ScalarValue
  right_value: ScalarValue
  delta: ScalarValue
  evaluation: 'BETTER' | 'WORSE' | 'SAME' | 'DIFFERENT' | 'NOT_EVALUATED'
  basis: string | null
}

export interface ActiveConditionIntent {
  intent_id: string
  metric: string
  comparator: string
  target_value: number
  priority_tier: number
  scope: Record<string, unknown> | null
}

export interface ActiveCondition {
  instance_id: string
  plugin_type: string
  plugin_version: string
  enabled: boolean
  scope: Record<string, unknown>
  config: Record<string, unknown>
  intent: ActiveConditionIntent | null
  // Epic A: semantic group (HARD / CAPABILITY / INTENT) derived by the
  // backend from the plugin registry; typeclass_ids = factory-mapped join
  // keys for derived results.
  semantic_group: string
  typeclass_ids: string[]
  // True for the engine's auto-attached year-round default clearing rule
  // (P00): shown with a "默认" tag, still removable.
  is_default?: boolean
  // V5 provenance (spec §18.11)
  source_kind: 'BASE' | 'SESSION' | 'BASE_SETTING' | 'SYSTEM'
  source_plan_version_id: string | null
  source_action_id: string | null
  actor: string | null
  created_at: string | null
  editable_in_current_session: boolean
}

// P00 Setup types (Phase A/B)

export interface SalesPlanVersion {
  sales_plan_version_id: string
  display_name: string
  status: string
}

export interface FactoryModelVersion {
  factory_model_version_id: string
  display_name: string
  status: string
  typeclass_ids?: string[]
  created_at?: string | null
}

export interface CalendarVersion {
  calendar_version_id: string
  display_name: string
  status: string
  calendar_year?: number | null
  covers_full_year?: boolean
  created_at?: string | null
}

export interface ActualRevision {
  actual_revision_id: string
  effective_date: string
  recorded_at: string
  supersedes_revision_id: string | null
  schema_version?: 1 | 2
  source_formal_pp_id?: string | null
  source_formal_fingerprint?: string | null
  calendar_year?: number | null
  actual_effective_date?: string | null
  effective_date_override_reason?: string | null
  workbook_declared_effective_date?: string | null
  workbook_sha256?: string | null
  canonical_actual_fingerprint?: string | null
}

export interface InitialStateSnapshot {
  initial_state_snapshot_id: string
  display_name: string
  status: string
  supersedes_initial_state_snapshot_id: string | null
  created_at: string
}

export interface InitialStateSnapshotDetail extends InitialStateSnapshot {
  initial_state: InitialStatePayload
}

// V5 WIP Target versioned soft input (spec §10)

export interface WipTargetItem {
  node_type: 'WORKSHOP' | 'BUFFER'
  node_id: string
  target_quantity: number
}

export interface WipTargetVersion {
  wip_target_version_id: string
  display_name: string
  status: string
  supersedes_wip_target_version_id: string | null
  created_at: string
}

export interface WipTargetVersionDetail extends WipTargetVersion {
  targets: WipTargetItem[]
}

export interface WipTargetCreateRequest {
  display_name: string
  targets: WipTargetItem[]
  supersedes_wip_target_version_id?: string | null
}

export interface InitialStatePayload {
  as_of_date: string
  finished_inventory_bod_by_typeclass: { typeclass_id: string; quantity: number }[]
  workshop_wip_by_typeclass: {
    workshop_id: string
    wip_bod_by_typeclass: { typeclass_id: string; quantity: number }[]
  }[]
  buffer_bod_by_typeclass: {
    buffer_id: string
    wip_bod_by_typeclass: { typeclass_id: string; quantity: number }[]
  }[]
  recent_flow_entries: any[]
  recent_accumulate_entries: any[]
}

export interface PreflightCheck {
  check: string
  ok: boolean
  detail: string
}

export interface ActualProtectedDateRange {
  start_date: string
  end_date: string
  lock_state: string
  lock_source: string
}

export interface PreflightResult {
  outcome: 'PASS' | 'BLOCKED'
  checks: PreflightCheck[]
  // Additive Actual scope projection. Optional keeps older, non-Actual
  // responses readable while callers can explicitly gate on API presence.
  actual_locked_through?: string | null
  mutable_replan_start?: string | null
  mutable_dates?: string[]
  protected_dates?: ActualProtectedDateRange[]
  explicit_locked_dates?: string[]
}

export interface StartSessionRequest {
  sales_plan_version_id: string
  factory_model_version_id: string
  calendar_version_id: string
  actual_revision_id?: string | null
  initial_state_snapshot_id?: string | null
  algorithm_profile?: Record<string, unknown> | null
  default_lock_days?: number | null
  resolved_locks?: any[] | null
  // F1 (V4 UI Final freeze): authorized delivery windows are context facts.
  // Golden fixtures must pass them explicitly.
  delivery_windows?: { typeclass_id: string; start_date: string; end_date: string; reason?: string }[] | null
  planning_conditions?: Record<string, unknown>[] | null
  // V5: versioned WIP Target soft input, annual year, Confirmed Base lineage
  // and the editable Work Note (spec §10, §18.14).
  wip_target_version_id?: string | null
  planning_year?: number | null
  base_confirmed_plan_version_id?: string | null
  work_note?: string | null
}

export interface GeneratePlanRequest {
  expected_planning_revision: number
}
