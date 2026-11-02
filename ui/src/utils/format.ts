import type { ScalarValue } from '../types/api'

export function displayValue(value: ScalarValue, unit?: string | null) {
  if (value === null || value === undefined || value === '') return '—'
  const number = typeof value === 'number' || (typeof value === 'string' && value.trim() !== '' && Number.isFinite(Number(value)))
    ? Number(value)
    : null
  const rendered = number === null ? String(value) : number.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  return unit ? `${rendered} ${unit}` : rendered
}

export function shortId(value: string | null | undefined) {
  if (!value) return '—'
  return value.length > 18 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value
}

export function formatDateTime(value: string | null | undefined) {
  if (!value) return '—'
  return new Intl.DateTimeFormat('zh-CN', { dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value))
}

export function formatDate(value: string | null | undefined) {
  if (!value) return '—'
  // Only pure "YYYY-MM-DD" gets the local-midnight suffix; full ISO
  // timestamps (recorded_at etc.) parse directly. Never construct an
  // invalid Date from a mismatched shape.
  const date = new Date(value.length === 10 ? `${value}T00:00:00` : value)
  if (Number.isNaN(date.getTime())) return value
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit', weekday: 'short' }).format(date)
}
