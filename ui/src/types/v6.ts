import type { AlgorithmProfile, AnnualCalendar, AnnualDay, AnnualMonth, EffectEvidenceStatus, MonthlyDay, MonthlyFilling, PlanningDayEffect, PlanningDayEffectsByNode } from './api'

export type V6GenerationMode = 'INITIAL_FROM_ZERO' | 'ROLLING_FROM_FORMAL_PP'
export type V6SessionStatus = 'OPEN' | 'CLOSED' | 'ABANDONED'
export type V6MonthlyMetric = Record<string, number> | 'NOT_EVALUATED'

export interface V6TypeclassMonthlyFact {
  pr: number
  fok: number
  gap: number
}

export interface V6TypeclassFact {
  annual_pr: number
  annual_fok: number
  annual_gap: number
  months: Record<string, V6TypeclassMonthlyFact>
}

export interface V6CommandResult {
  ok: boolean
  outcome_type: string
  outcome: string
  message: string
  payload?: Record<string, unknown>
  error_code?: string
  session_id?: string
  candidate_id?: string
  formal_pp_id?: string
  planning_revision?: number
  candidate_revision?: number
  draft_id?: string
  draft_revision?: number
  status?: string
  approval_token?: string
  warning_codes?: string[]
  hard_error_codes?: string[]
  formal_save_allowed?: boolean
  validation_status?: string
  restored_from_session_id?: string
  restored_from_candidate_id?: string
  missing_information?: string[]
  errors?: unknown[]
  problems?: unknown[]
  session_cleanup?: Record<string, unknown> | string | null
}

export type V6ActualFillingPreviewOutcome = 'PASS' | 'BLOCKED'

export interface V6ActualFillingImportIssue {
  error_code: string
  severity: string
  sheet: string | null
  cell: string | null
  month: string | null
  date: string | null
  workshop_id: string | null
  node_id: string | null
  typeclass_id: string | null
  field: string | null
  actual_value: unknown
  expected_value: unknown
  gap: unknown
  message: string
  suggestion: string | null
}

export interface V6ActualFillingPreviewResponse {
  outcome: V6ActualFillingPreviewOutcome
  workbook_sha256: string
  preview_fingerprint: string
  workbook_schema: string
  calendar_year: number
  source_formal_pp_id: string
  source_formal_fingerprint: string
  workbook_declared_effective_date: string | null
  confirmed_effective_date: string
  coverage_summary: Record<string, unknown>
  diff_from_superseded_actual: Record<string, unknown> | null
  issues: V6ActualFillingImportIssue[]
}

export interface V6ActualFillingImportBaseRequest {
  file: File
  confirmedEffectiveDate: string
  supersedesActualRevisionId?: string | null
}

export interface V6ActualFillingPreviewRequest extends V6ActualFillingImportBaseRequest {
  reason?: string
}

export interface V6ActualFillingApplyRequest extends V6ActualFillingImportBaseRequest {
  expectedWorkbookSha256: string
  expectedPreviewFingerprint: string
  reason: string
  idempotencyKey: string
}

export interface V6ActualFillingErrorReportRequest extends V6ActualFillingImportBaseRequest {
  expectedWorkbookSha256: string
  expectedPreviewFingerprint: string
  reason?: string
}

export interface V6ActualFillingApplyResponse {
  outcome: 'CREATED' | 'IDEMPOTENT_REPLAY'
  actual_revision_id: string
  schema_version: 2
  source_formal_pp_id: string
  source_formal_fingerprint: string
  calendar_year: number
  actual_effective_date: string
  canonical_actual_fingerprint: string
}

export interface V6MonthlyDemandFact {
  month: string
  typeclass_id: string
  quantity: number
}

export interface V6PRVersion {
  pr_version_id: string
  business_id: string
  display_name: string
  status: string
  months: V6MonthlyDemandFact[]
  source: string
  supersedes_pr_version_id: string | null
  created_at: string
}

export interface V6WSVersion {
  ws_version_id: string
  business_id: string
  display_name: string
  status: string
  months: V6MonthlyDemandFact[]
  source: string
  supersedes_ws_version_id: string | null
  created_at: string
}

export interface V6BusinessIdSnapshot {
  kind: string
  version_id: string
  business_id: string
}

export interface V6InputBundle {
  pr_version_id: string
  ws_version_id: string | null
  factory_version_id: string
  calendar_version_id: string
  initial_state_version_id: string
  wip_policy_version_id: string
  actual_revision_id: string | null
  condition_snapshot: { items: Record<string, unknown>[] }
  algorithm_profile: AlgorithmProfile
  algorithm_engine_version: string
  algorithm_profile_version_id: string | null
  generation_mode: V6GenerationMode
  parent_formal_pp_id: string | null
  fix_months: string[]
  resolved_locks: Record<string, unknown>[]
  business_id_snapshots: V6BusinessIdSnapshot[]
}

export interface V6Session {
  session_id: string
  generation_mode: V6GenerationMode
  parent_formal_pp_id: string | null
  input_bundle: V6InputBundle
  current_candidate_id: string | null
  planning_revision: number
  status: V6SessionStatus
  work_note: string | null
  started_at: string
  closed_at: string | null
}

export interface V6CandidateHistoryItem {
  candidate_id: string
  parent_candidate_id: string | null
  candidate_revision: number
  generation_reason: string
  validation_status: string
  warning_codes: string[]
  hard_error_codes: string[]
  created_at: string
  is_current: boolean
}

export interface V6DemandAuthorizationEvidence {
  annual_pr_by_typeclass: Record<string, number>
  pre_holiday_as_output: Record<string, number>
  first_outcome_discrete_overdelivery: Record<string, number>
  authorized_surplus: Record<string, number>
  annual_output_ceiling: Record<string, number>
  basis: string
}

export interface V6AnnualOutputContractEvidence {
  annual_pr: Record<string, number>
  pre_holiday_physical_as_out: Record<string, number>
  first_outcome_evidenced_surplus: Record<string, number>
  authorized_surplus: Record<string, number>
  fixed_annual_output_target: Record<string, number>
  annual_output_ceiling: Record<string, number>
  target_source: string
}

export interface V6OpenedActivityDay {
  date: string
  typeclass_id: string
  workshop_ids: string[]
  planned_in: number
  planned_out: number
  mutable: boolean
  source: 'CONTROLLED_ACTIVITY_EXTENSION'
  capacity_by_workshop: Record<string, number>
  mode_by_workshop: Record<string, string>
  before_plan_fingerprint: string
  after_plan_fingerprint: string
}

export interface V6WindowLineage {
  ancestor: V6IssueWindowSummary | null
  descendant: V6IssueWindowSummary | null
  fragments: V6IssueWindowSummary[]
  causing_opened_dates: string[]
  classification: string
}

export interface V6FinalSemanticDiff {
  blocking: boolean
  uncovered_long_window: boolean
  core_signature_unchanged: boolean
  core_opened_intersection: boolean
  noncore_lineage_safe: boolean
  nonclearing_zero_flow_unchanged: boolean
  requires_clearing_lineage: V6WindowLineage[]
}

export interface V6HolidayReconciliationEvidence {
  before_repair_as_out: Record<string, number>
  after_first_repair_as_out: Record<string, number>
  raw_repair_loss: Record<string, Record<string, number>>
  bounded_recovery_output?: Record<string, Record<string, number>>
  protected_transition_hash: string | null
  protected_transition_count: number
  exact_replan_attempted: boolean
  exact_replan_realized_output: Record<string, number> | null
  final_as_out?: Record<string, number>
  final_delta_to_target: Record<string, number>
  blocking_codes?: string[]
  failure_detail?: string
  opened_activity_refs?: string[]
  opened_activity_days?: V6OpenedActivityDay[]
  opened_activity_count?: number
  opened_activity_hash?: string | null
  wip_trajectory_unchanged?: boolean
  wip_trajectory_reconciled?: boolean
  final_semantic_diff?: V6FinalSemanticDiff | null
  diff_basis?: string
  exact_window_anchor?: V6IssueWindowSummary[]
  window_change_notice?: {
    status: 'INFORMATIONAL'
    message: string
    opened_activity_days: V6OpenedActivityDay[]
    lineage: V6WindowLineage[]
  }
  historical_shutdown_effects?: Record<string, unknown>[]
  shared_wip_reconciliation?: {
    status: 'APPLIED' | 'UNCHANGED' | 'NOT_APPLICABLE' | 'BLOCKED'
    adjusted_decision_refs?: string[]
    before_wbs?: Record<string, number>
    after_wbs?: Record<string, number>
    annual_as_output_unchanged?: boolean
    welding_wip_unchanged?: boolean
  }
}

export interface V6IssueWindowSummary {
  window_id: string | null
  kind: string | null
  start_date: string | null
  end_date: string | null
  workshop_id: string | null
  typeclass_id: string | null
  requires_clearing: boolean | null
  zero_flow_days: (string | null)[]
  preholiday_targets: Record<string, number | null> | null
  refill_targets: Record<string, number | null> | null
}

export interface V6CandidateIssueDetail {
  code: string
  severity: 'ERROR' | 'WARNING'
  source: 'EXACT_TRANSITION' | 'HOLIDAY_REPAIR' | 'VALIDATION' | 'HOLIDAY_DIFF' | 'PROBLEM'
  detail: string
  date: string | null
  start_date: string | null
  end_date: string | null
  window_id: string | null
  workshop_id: string | null
  node_kind: 'WORKSHOP' | 'BUFFER' | 'INVENTORY' | null
  node_id: string | null
  typeclass_id: string | null
  target: number | null
  actual: number | null
  quantity_scope?: 'TYPECLASS' | 'NODE_TOTAL' | null
  change_type: 'ADDED' | 'REMOVED' | 'CHANGED' | null
  before_window: V6IssueWindowSummary | null
  after_window: V6IssueWindowSummary | null
}

export interface V6CandidateFacts {
  candidate_id: string
  session_id: string
  parent_candidate_id: string | null
  candidate_revision: number
  planning_revision: number
  generation_reason: string
  generation_mode: V6GenerationMode
  input_fingerprint: string
  input_bindings: Record<string, string | null>
  pr_by_month: Record<string, number>
  pr_total: number
  ws_by_month: V6MonthlyMetric
  ws_total: number | 'NOT_EVALUATED'
  pp_by_month: Record<string, number>
  pp_total: number
  typeclass_facts: Record<string, V6TypeclassFact>
  yard_stock_by_month: V6MonthlyMetric
  yard_stock: number | 'NOT_EVALUATED'
  production_day_by_month: Record<string, number>
  production_day_count: number
  pending_day_by_month: Record<string, number>
  pending_day_count: number
  overtime_by_month: Record<string, number>
  overtime_day_count: number
  potential_volume_by_month: Record<string, number>
  potential_volume_total: number
  conditions: Record<string, unknown>[]
  condition_evidence_status: 'EVALUATED' | 'NOT_EVALUATED'
  condition_results: V6ConditionExecutionResult[]
  condition_evaluation_summary: {
    condition_count: number
    replay_count: number
    counterfactual_fingerprints: { condition_id: string; fingerprint: string }[]
  } | null
  holiday_windows: Record<string, unknown>[]
  holiday_iteration: Record<string, unknown> | null
  composite_stop_blocks: V6CompositeStopBlock[]
  workday_relocations: V6WorkdayRelocation[]
  adjacent_stop_merge_diagnostics: Record<string, unknown>[]
  demand_authorization: V6DemandAuthorizationEvidence | null
  annual_output_contract: V6AnnualOutputContractEvidence | null
  holiday_reconciliation: V6HolidayReconciliationEvidence | null
  final_wip: Record<string, number>
  problems: V6CandidateProblem[]
  issue_details: V6CandidateIssueDetail[]
  validation: Record<string, unknown> | null
  warning_codes: string[]
  hard_error_codes: string[]
  created_at: string
}

export interface V6ConditionExecutionResult {
  condition_id: string
  plugin_type: string
  status: 'APPLIED' | 'NOT_APPLICABLE' | 'BLOCKED'
  plan_impact: 'PLAN_CHANGED' | 'NO_PLAN_CHANGE'
  reason_code: string
  effect_ids: string[]
}

export interface V6HolidayBoundaryNote {
  code:
    | 'HORIZON_START_INPUT_PRESERVED'
    | 'HORIZON_END_REFILL_NOT_APPLICABLE'
    | 'DEPENDENCY_REFILL_DELAYED'
    | 'DEPENDENCY_REFILL_NOT_APPLICABLE'
  side: 'BEFORE' | 'AFTER'
  node_id: string | null
  current_wip: number | null
  target_wip: number | null
  effective_date?: string | null
  blocking_workshop_ids?: string[]
  blocked_typeclass_ids?: string[]
  source_window_start?: string | null
  source_window_end?: string | null
  detail: string
  window: Record<string, unknown>
}

export interface V6CompositeStopBlock {
  composite_window_id: string
  workshop_id: string
  typeclass_id: string
  original_start_date: string
  original_end_date: string
  effective_stop_end_date: string
  member_window_ids: string[]
  member_source_condition_ids: string[]
  affected_workshop_ids: string[]
  gap_workdays: number
  refill_required_days: number
  clearing_required_days: number
  source_workdays: string[]
  destination_workdays: string[]
  extended_beyond_original_end: boolean
  reason: string
}

export interface V6WorkdayRelocation {
  composite_window_id: string
  source_workdays: string[]
  destination_workdays: string[]
  extended_beyond_original_end: boolean
  original_start_date: string
  original_end_date: string
  effective_stop_end_date: string
  member_window_ids: string[]
  member_source_condition_ids: string[]
  source_lock_states: { date: string; lock_state: string }[]
  cross_month: boolean
  pre_relocation_plan_fingerprint: string
  post_relocation_plan_fingerprint: string | null
  provenance: string[]
}

export type V6CandidateMonthlyDay = MonthlyDay & {
  shutdown_day: boolean
  special_effects: PlanningDayEffect[]
  effects_by_node: PlanningDayEffectsByNode
  condition_result_refs: string[]
}

export type V6CandidateMonthlyFilling = Omit<MonthlyFilling, 'plan_version_id' | 'days'> & {
  candidate_id: string
  candidate_revision: number
  effect_evidence_status: EffectEvidenceStatus
  days: V6CandidateMonthlyDay[]
  boundary_notes: V6HolidayBoundaryNote[]
  composite_stop_blocks: V6CompositeStopBlock[]
  workday_relocations: V6WorkdayRelocation[]
  demand_authorization: V6DemandAuthorizationEvidence | null
  annual_output_contract: V6AnnualOutputContractEvidence | null
  holiday_reconciliation: V6HolidayReconciliationEvidence | null
}

export type V6CandidateAnnualDay = AnnualDay & {
  special_effects: PlanningDayEffect[]
  effects_by_node: PlanningDayEffectsByNode
  condition_result_refs: string[]
}

export type V6CandidateAnnualMonth = Omit<AnnualMonth, 'days'> & {
  days: V6CandidateAnnualDay[]
}

export type V6CandidateAnnualOverview = Omit<AnnualCalendar, 'plan_version_id' | 'months' | 'days'> & {
  candidate_id: string
  candidate_revision: number
  effect_evidence_status: EffectEvidenceStatus
  months: V6CandidateAnnualMonth[]
  days: V6CandidateAnnualDay[]
  holiday_windows: Record<string, unknown>[]
  boundary_notes: V6HolidayBoundaryNote[]
  composite_stop_blocks: V6CompositeStopBlock[]
  workday_relocations: V6WorkdayRelocation[]
  demand_authorization: V6DemandAuthorizationEvidence | null
  annual_output_contract: V6AnnualOutputContractEvidence | null
  holiday_reconciliation: V6HolidayReconciliationEvidence | null
  typeclass_facts: Record<string, V6TypeclassFact>
  hard_error_codes: string[]
  warning_codes: string[]
}

export interface V6CandidateProblem {
  code: string
  issue_type: string
  month: string
  typeclass_id: string
  required: number
  realizable: number
  gap: number
  detail: string
}

export interface V6ConditionProposal {
  proposal_id: string
  selector_type: string
  selector_id: string
  scope: Record<string, unknown>
  params: Record<string, unknown>
  reason: string
  referenced_business_ids: string[]
  builder_result: Record<string, unknown>
  validation_errors: string[]
}

export type V6ConditionSelectorType = 'ACTION' | 'INTENT'

export interface V6ConditionOption {
  selector_type: V6ConditionSelectorType
  selector_id: string
  label: string
  category: string
  description: string
  editor_kind: string
  supports_batch: boolean
  semantic_type: string
}

export interface V6ConditionOptionInventory {
  options: V6ConditionOption[]
}

export interface V6ConditionComposerValue {
  selectorType: V6ConditionSelectorType
  selectorId: string
  params: Record<string, unknown>
  reason: string
}

export interface V6ConditionDraft {
  draft_id: string
  session_id: string
  parent_candidate_id: string
  planning_revision: number
  draft_revision: number
  input_fingerprint: string
  raw_text: string
  status: string
  proposal_items: V6ConditionProposal[]
  canonical_conditions: Record<string, unknown>[]
  missing_information: string[]
  trace: Record<string, unknown> | null
  created_at: string
  updated_at: string
  expires_at: string | null
}

export interface V6SaveGate {
  technical_save_allowed: boolean
  formal_save_allowed: boolean
  blockers: { code: string; detail: unknown }[]
  warning_codes_requiring_acknowledgement: string[]
  unsafe_demo_override: boolean
  unsafe_demo_hard_error_codes: string[]
}

export interface V6Workbench {
  session: V6Session
  current_candidate: V6CandidateFacts | null
  viewed_candidate: V6CandidateFacts | null
  candidate_history: V6CandidateHistoryItem[]
  condition_drafts: V6ConditionDraft[]
  save_gate: V6SaveGate
}

export interface V6SessionStartRequest {
  generation_mode: V6GenerationMode
  pr_version_id: string
  ws_version_id?: string | null
  parent_formal_pp_id?: string | null
  factory_version_id?: string | null
  calendar_version_id?: string | null
  initial_state_version_id?: string | null
  wip_policy_version_id?: string | null
  actual_revision_id?: string | null
  planning_conditions?: Record<string, unknown>[] | null
  algorithm_profile?: Record<string, unknown> | null
  fix_months?: string[]
  work_note?: string | null
  actor?: string
}

export interface V6FormalPPVersion {
  formal_pp_id: string
  formal_fingerprint: string
  display_name: string
  source_session_id: string
  source_candidate_id: string
  parent_formal_pp_id: string | null
  input_bundle: V6InputBundle
  plan: Record<string, unknown> & {
    horizon_start: string
    horizon_end: string
  }
  context_snapshot: Record<string, unknown>
  validation: Record<string, unknown> | null
  candidate_evidence: Record<string, unknown>
  warning_acknowledgements: Record<string, unknown>[]
  work_note: string
  saved_by: string
  saved_at: string
}

export interface V6FormalProjectionIdentity {
  source_kind: 'FORMAL_PP'
  source_id: string
  formal_pp_id: string
  formal_fingerprint: string
  source_candidate_id: string
  source_session_id: string
  display_name: string
  saved_at: string
  read_only: true
}

export type V6FormalAnnualOverview = Omit<
  V6CandidateAnnualOverview,
  'candidate_id' | 'candidate_revision'
> & V6FormalProjectionIdentity

export type V6FormalMonthlyFilling = Omit<
  V6CandidateMonthlyFilling,
  'candidate_id' | 'candidate_revision'
> & V6FormalProjectionIdentity

export type V6ProjectionViewIdentity =
  | {
      kind: 'CANDIDATE'
      sourceId: string
      revision: number
    }
  | {
      kind: 'FORMAL_PP'
      sourceId: string
      displayName: string
      savedAt: string
      sourceCandidateId: string
      fingerprint: string
      readOnly: true
    }

export interface V6FormalFacts extends V6CandidateFacts {
  formal_pp_id: string
  formal_fingerprint: string
  display_name: string
  source_session_id: string
  parent_formal_pp_id: string | null
  warnings: Record<string, unknown>[]
}

export interface V6FormalComparison {
  base_formal_pp_id: string
  compared_formal_pp_id: string
  delta: Record<string, number | 'NOT_EVALUATED'>
  monthly_delta: Record<string, V6MonthlyMetric>
  changed_inputs: string[]
  input_diff: Record<string, { before: unknown; after: unknown }>
  changed_conditions: boolean
  condition_diff: V6RecordDiff
  changed_condition_results: boolean
  condition_result_diff: V6RecordDiff
  changed_holiday_windows: boolean
  holiday_window_diff: V6RecordDiff
  wip_delta: Record<string, number>
  warning_diff: V6RecordDiff
  changed_formal_fingerprint: boolean
  changed_demand_authorization: boolean
  demand_authorization_diff: { before: V6DemandAuthorizationEvidence | null; after: V6DemandAuthorizationEvidence | null }
  changed_annual_output_contract: boolean
  annual_output_contract_diff: { before: V6AnnualOutputContractEvidence | null; after: V6AnnualOutputContractEvidence | null }
  changed_holiday_reconciliation: boolean
  holiday_reconciliation_diff: { before: V6HolidayReconciliationEvidence | null; after: V6HolidayReconciliationEvidence | null }
}

export interface V6RecordDiff {
  added: Record<string, unknown>[]
  removed: Record<string, unknown>[]
  changed: { before: Record<string, unknown>; after: Record<string, unknown> }[]
}

export interface V6FormalCompareResponse {
  baseline_formal_pp_id: string
  formal_versions: V6FormalFacts[]
  comparisons: V6FormalComparison[]
}
