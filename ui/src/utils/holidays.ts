// 2024~2030 企业日历共同事实源。2024~2026 是国务院年度安排；
// 2027~2030 只包含现行法定节日本日和周末，不猜测尚未公布的连休/调休。

import calendarBaseline from '../data/cnCalendarBaseline.json'

export const CALENDAR_YEAR_MIN = 2024
export const CALENDAR_YEAR_MAX = 2030

export type YearDayStatus = 'prod' | 'off'

export type YearDay = {
  date: string        // YYYY-MM-DD
  wd: string          // 周一..周日
  status: YearDayStatus
  label: string       // 节假日名 / "班"（调休上班）/ ''
}

export type CalendarBasis = 'official-annual-arrangement' | 'statutory-days-only'

type HolidayBaseline = {
  name: string
  off_ranges: [string, string][]
}

type YearBaseline = {
  basis: CalendarBasis
  holidays: HolidayBaseline[]
  work_dates: string[]
}

const YEAR_BASELINES = calendarBaseline.years as unknown as Record<string, YearBaseline>

export function calendarBasis(year: number): CalendarBasis | null {
  return YEAR_BASELINES[String(year)]?.basis ?? null
}

export function hasCalendarBaseline(year: number): boolean {
  return calendarBasis(year) !== null
}

export function hasOfficialHolidayData(year: number): boolean {
  return calendarBasis(year) === 'official-annual-arrangement'
}

export const WORK_LABEL = '班'

const WEEKDAY_CN = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

function spanDays(year: number, start: string, finish: string): string[] {
  const out: string[] = []
  const cur = new Date(`${year}-${start}T00:00:00`)
  const end = new Date(`${year}-${finish}T00:00:00`)
  if (Number.isNaN(cur.getTime()) || Number.isNaN(end.getTime()) || cur > end) {
    throw new Error(`${year} 年日历基线日期区间无效: ${start}..${finish}`)
  }
  while (cur <= end) {
    if (cur.getFullYear() !== year) throw new Error(`${year} 年日历基线不得跨年`)
    out.push(`${String(cur.getMonth() + 1).padStart(2, '0')}-${String(cur.getDate()).padStart(2, '0')}`)
    cur.setDate(cur.getDate() + 1)
  }
  return out
}

/** 全年逐日默认日历：调休上班日 → 生产（标"班"）；周末 → 休；
 *  放假区间 → 休（标节日名）；其余 → 生产。 */
export function defaultYearDays(year: number): YearDay[] {
  const baseline = YEAR_BASELINES[String(year)]
  if (!baseline) throw new Error(`${year} 年企业日历基线待维护`)
  const off = new Map<string, string>()   // "M-D" → 节日名
  const work = new Set<string>()          // "M-D" 调休上班日
  for (const holiday of baseline.holidays) {
    for (const [start, finish] of holiday.off_ranges) {
      for (const md of spanDays(year, start, finish)) off.set(md, holiday.name)
    }
  }
  for (const md of baseline.work_dates) work.add(md)
  const days: YearDay[] = []
  const d = new Date(year, 0, 1)
  while (d.getFullYear() === year) {
    const key = `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
    let status: YearDayStatus = 'prod'
    let label = ''
    if (work.has(key)) {
      status = 'prod'
      label = WORK_LABEL
    } else if (off.has(key)) {
      status = 'off'
      label = off.get(key) || ''
    } else if (d.getDay() === 0 || d.getDay() === 6) {
      status = 'off'
    }
    days.push({
      date: `${year}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`,
      wd: WEEKDAY_CN[d.getDay() === 0 ? 6 : d.getDay() - 1],
      status,
      label,
    })
    d.setDate(d.getDate() + 1)
  }
  return days
}
