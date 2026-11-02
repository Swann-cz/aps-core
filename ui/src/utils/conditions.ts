import type { ActiveCondition } from '../types/api'

// Business-language labels + semantic-group colors for planner-attached
// conditions. UI wording only — backend semantics never altered.
const GROUP_COLORS: Record<string, string> = {
  HARD: 'red',
  CAPABILITY: 'purple',
  INTENT: 'blue',
}

const PLUGIN_LABELS: Record<string, string> = {
  capacity_loss: '产能损失',
  clearing: '停线前清线',
  fixed_output: '固定产出',
  line_refill: '复线灌线',
  ramp_up: '复线爬坡',
  shutdown: '放假停线',
  forbid_working_mode: '禁止加班',
  saturday_capability: '周六生产',
  working_mode_capability: '工作模式',
  avoid_saturday_intent: '少用周六',
  wbs_water_level: 'WBS 摆线水位',
}

const ACTION_LABELS: Record<string, string> = {
  SHUTDOWN: '放假 / 停线',
  CLEARING: '清线规则 / 人工清线窗口',
  RAMP_UP: '复线爬坡',
  WBS_LEVEL: 'WBS 摆线水位',
  FORBID_WORKING_MODE: '禁止加班模式',
  CAPACITY_LOSS: '产能受限',
  ENABLE_SATURDAY: '启用周六生产',
  ENABLE_WORKING_MODE: '启用工作模式',
}

export function conditionActionLabel(actionType: string): string {
  return ACTION_LABELS[actionType] ?? '其他排产条件'
}

export type ConditionBadge = {
  key: string
  label: string
  color: string
  group: string
}

export function conditionColor(group: string): string {
  return GROUP_COLORS[group] ?? 'default'
}

export function conditionLabel(condition: ActiveCondition): string {
  const base = PLUGIN_LABELS[condition.plugin_type] ?? condition.plugin_type
  if (condition.plugin_type === 'forbid_working_mode') {
    const mode = String(condition.config.working_mode_id ?? '')
    return `${base} ${mode.replace('SINGLE_', '').replace('8P2', '8+2').replace('8P1', '8+1').replace('8H', '8小时')}`
  }
  if (condition.plugin_type === 'working_mode_capability') {
    const mode = String(condition.config.working_mode_id ?? '')
    return `${base} ${mode.replace('SINGLE_', '').replace('8P2', '8+2').replace('8P1', '8+1').replace('8H', '8小时')}`
  }
  if (condition.plugin_type === 'shutdown' && condition.config.reason) {
    return `${base}·${String(condition.config.reason)}`
  }
  if (condition.plugin_type === 'clearing') {
    const isRule = !Array.isArray(condition.scope.workshop_ids) || condition.scope.workshop_ids.length === 0
    return isRule ? '全年清线策略（需停线条件触发）' : base
  }
  if (condition.plugin_type === 'line_refill') {
    const drained = Number(condition.config.drained_internal_wip ?? 0)
    return drained > 0 ? `${base} ${drained}台` : base
  }
  if (condition.plugin_type === 'ramp_up') {
    const curve = Array.isArray(condition.config.daily_jph_ceilings)
      ? condition.config.daily_jph_ceilings.join('→')
      : ''
    return curve ? `${base} ${curve} JPH` : base
  }
  return base
}

export function conditionAppliesOnDate(condition: ActiveCondition, date: string): boolean {
  const start = condition.scope.start_date as string | undefined
  const end = condition.scope.end_date as string | undefined
  if (start && date < start) return false
  if (end && date > end) return false
  return true
}

function nextIsoDate(value: string): string {
  const [year, month, day] = value.split('-').map(Number)
  const next = new Date(Date.UTC(year, month - 1, day + 1))
  const yyyy = String(next.getUTCFullYear()).padStart(4, '0')
  const mm = String(next.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(next.getUTCDate()).padStart(2, '0')
  return `${yyyy}-${mm}-${dd}`
}

/** Index active conditions by date → stacked badges (deterministic order). */
export function conditionsByDate(conditions: ActiveCondition[]): Record<string, ConditionBadge[]> {
  const byDate: Record<string, ConditionBadge[]> = {}
  const sorted = [...conditions].sort((a, b) =>
    a.plugin_type.localeCompare(b.plugin_type) || a.instance_id.localeCompare(b.instance_id),
  )
  for (const condition of sorted) {
    if (!condition.enabled) continue
    // Year-round rule markers (clearing rule, WBS water level, refill rule)
    // are declarations, not per-day operations: they must NOT paint a daily
    // badge across every date. Only concrete scoped windows show a badge.
    if (
      (condition.plugin_type === 'clearing'
        && (condition.scope.workshop_ids as unknown[] | undefined)?.length === 0)
      || condition.plugin_type === 'wbs_water_level'
    ) {
      continue
    }
    const start = (condition.scope.start_date as string | undefined) ?? ''
    const end = (condition.scope.end_date as string | undefined) ?? start
    if (!start || !end) continue
    const badge: ConditionBadge = {
      key: condition.instance_id,
      label: conditionLabel(condition),
      color: conditionColor(condition.semantic_group),
      group: condition.semantic_group,
    }
    // Iterate the bounded date span of the condition and stamp its days.
    let iso = start
    while (iso <= end) {
      const list = byDate[iso] ?? (byDate[iso] = [])
      if (!list.some((item) => item.key === badge.key)) list.push(badge)
      iso = nextIsoDate(iso)
    }
  }
  return byDate
}
