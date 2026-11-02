import type { AnnualDay, PreflightResult } from '../../types/api'
import type { ChangeSource, PreflightEnvelope } from './types'

export interface CompleteActualScope extends PreflightResult {
  actual_locked_through: string | null
  mutable_replan_start: string | null
  mutable_dates: string[]
  protected_dates: NonNullable<PreflightResult['protected_dates']>
  explicit_locked_dates: string[]
}

const SCOPE_FIELDS = [
  'actual_locked_through',
  'mutable_replan_start',
  'mutable_dates',
  'protected_dates',
  'explicit_locked_dates',
] as const

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isIsoDateInYear(value: unknown, planningYear: number): value is string {
  if (typeof value !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(value)) return false
  const [year, month, day] = value.split('-').map(Number)
  if (year !== planningYear) return false
  const parsed = new Date(Date.UTC(year, month - 1, day))
  return parsed.getUTCFullYear() === year
    && parsed.getUTCMonth() === month - 1
    && parsed.getUTCDate() === day
}

export function validatedBaseDays(
  projection: unknown,
  planVersionId: string | null,
  planningYear: number | null,
): AnnualDay[] | null {
  if (!isRecord(projection) || !planVersionId || planningYear === null) return null
  if (projection.plan_version_id !== planVersionId || !Array.isArray(projection.days)) return null
  const expectedDates = new Set<string>()
  const cursor = new Date(Date.UTC(planningYear, 0, 1))
  while (cursor.getUTCFullYear() === planningYear) {
    expectedDates.add(cursor.toISOString().slice(0, 10))
    cursor.setUTCDate(cursor.getUTCDate() + 1)
  }
  if (projection.days.length !== expectedDates.size) return null
  const seenDates = new Set<string>()
  const valid = projection.days.every((day) => {
    if (
      !isRecord(day)
      || !isIsoDateInYear(day.date, planningYear)
      || !expectedDates.has(day.date)
      || seenDates.has(day.date)
      || !['ACTUALIZED', 'LOCKED', 'MUTABLE'].includes(String(day.lock_state))
      || !(
        day.lock_source === null
        || ['ACTUALIZED', 'DEFAULT_LOCK', 'EXPLICIT_LOCK'].includes(String(day.lock_source))
      )
    ) return false
    seenDates.add(day.date)
    return true
  })
  return valid && seenDates.size === expectedDates.size ? projection.days as AnnualDay[] : null
}

export function validatedPreflight(preflight: unknown): PreflightResult | null {
  if (!isRecord(preflight) || (preflight.outcome !== 'PASS' && preflight.outcome !== 'BLOCKED')) return null
  if (!Array.isArray(preflight.checks)) return null
  const checksValid = preflight.checks.every((check) => (
    isRecord(check)
    && typeof check.check === 'string'
    && check.check.length > 0
    && typeof check.ok === 'boolean'
    && typeof check.detail === 'string'
  ))
  return checksValid ? preflight as unknown as PreflightResult : null
}

export function isCurrentPreflight(
  inputsIdentity: string | null,
  preflight: PreflightEnvelope | undefined,
  fetching: boolean,
  error: boolean,
): boolean {
  return Boolean(
    inputsIdentity
    && preflight?.inputsIdentity === inputsIdentity
    && !fetching
    && !error,
  )
}

export function validatedActualScope(
  source: ChangeSource,
  preflightValue: unknown,
  planningYear: number,
): CompleteActualScope | null {
  const preflight = validatedPreflight(preflightValue)
  if (!preflight || !SCOPE_FIELDS.every((field) => Object.prototype.hasOwnProperty.call(preflight, field))) {
    return null
  }
  if (
    !(preflight.actual_locked_through === null || isIsoDateInYear(preflight.actual_locked_through, planningYear))
    || !(preflight.mutable_replan_start === null || isIsoDateInYear(preflight.mutable_replan_start, planningYear))
    || !Array.isArray(preflight.mutable_dates)
    || !preflight.mutable_dates.every((date) => isIsoDateInYear(date, planningYear))
    || !Array.isArray(preflight.explicit_locked_dates)
    || !preflight.explicit_locked_dates.every((date) => isIsoDateInYear(date, planningYear))
    || !Array.isArray(preflight.protected_dates)
  ) return null

  const protectedDatesValid = preflight.protected_dates.every((range) => (
    isRecord(range)
    && isIsoDateInYear(range.start_date, planningYear)
    && isIsoDateInYear(range.end_date, planningYear)
    && range.start_date <= range.end_date
    && typeof range.lock_state === 'string'
    && range.lock_state.length > 0
    && typeof range.lock_source === 'string'
    && range.lock_source.length > 0
  ))
  if (!protectedDatesValid) return null
  if (
    preflight.actual_locked_through
    && preflight.mutable_replan_start
    && preflight.actual_locked_through >= preflight.mutable_replan_start
  ) return null

  if (source === 'actual' || source === 'combined') {
    const actualCheck = preflight.checks.find((check) => check.check === 'actual_lock_scope_consistent')
    if (actualCheck?.ok !== true) return null
    if (preflight.mutable_dates.length === 0 && preflight.protected_dates.length === 0) return null
  }

  return preflight as CompleteActualScope
}
