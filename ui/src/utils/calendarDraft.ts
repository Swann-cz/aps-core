import type { YearCalendarResult } from '../components/YearCalendar'
import {
  CALENDAR_YEAR_MAX,
  CALENDAR_YEAR_MIN,
  defaultYearDays,
} from './holidays'

export type CalendarDraftDay = {
  date: string
  is_working_capable: boolean
  reason: string
}

export type CalendarDraftsByYear = Record<number, CalendarDraftDay[]>

function sortedDays(days: Iterable<CalendarDraftDay>): CalendarDraftDay[] {
  return Array.from(days).sort((left, right) => left.date.localeCompare(right.date))
}

export function defaultCalendarYear(year: number): CalendarDraftDay[] {
  if (year < CALENDAR_YEAR_MIN || year > CALENDAR_YEAR_MAX) {
    throw new Error(`企业日历年份越界: ${year}`)
  }
  return defaultYearDays(year).map((day) => ({
    date: day.date,
    is_working_capable: day.status === 'prod',
    reason: day.label,
  }))
}

export function calendarYears(days: CalendarDraftDay[]): number[] {
  return Array.from(new Set(days.map((day) => Number(day.date.slice(0, 4)))))
    .filter((year) => Number.isInteger(year))
    .sort((left, right) => left - right)
}

export function assertCompleteCalendarYear(
  days: CalendarDraftDay[],
  year: number,
): void {
  const expected = defaultCalendarYear(year).map((day) => day.date)
  const actual = sortedDays(days)
  if (actual.length !== expected.length) {
    throw new Error(`${year} 年企业日历必须包含全部 ${expected.length} 天`)
  }
  for (let index = 0; index < expected.length; index += 1) {
    if (actual[index]?.date !== expected[index]) {
      throw new Error(
        `${year} 年企业日历日期缺失或重复: `
        + `expected=${expected[index]} actual=${actual[index]?.date ?? 'none'}`,
      )
    }
  }
}

export function calendarDraftForYear(
  savedDays: CalendarDraftDay[],
  year: number,
): CalendarDraftDay[] {
  const byDate = new Map(defaultCalendarYear(year).map((day) => [day.date, day]))
  for (const day of savedDays) {
    if (day.date.startsWith(`${year}-`) && byDate.has(day.date)) {
      byDate.set(day.date, { ...day, reason: day.reason ?? '' })
    }
  }
  const result = sortedDays(byDate.values())
  assertCompleteCalendarYear(result, year)
  return result
}

export function sameCalendarDays(
  left: CalendarDraftDay[],
  right: CalendarDraftDay[],
): boolean {
  return left.length === right.length && left.every((day, index) => (
    day.date === right[index]?.date
    && day.is_working_capable === right[index]?.is_working_capable
    && day.reason === right[index]?.reason
  ))
}

export function setCalendarYearDraft(
  current: CalendarDraftsByYear,
  year: number,
  replacement: YearCalendarResult,
): CalendarDraftsByYear {
  const result = replacement.map((day) => ({ ...day, reason: day.reason ?? '' }))
  assertCompleteCalendarYear(result, year)
  const normalized = sortedDays(result)
  if (current[year] && sameCalendarDays(current[year], normalized)) return current
  return { ...current, [year]: normalized }
}
