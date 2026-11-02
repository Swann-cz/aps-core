import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { LeftOutlined, RightOutlined } from '@ant-design/icons'
import {
  CALENDAR_YEAR_MAX,
  CALENDAR_YEAR_MIN,
  WORK_LABEL,
  calendarBasis,
  defaultYearDays,
  type YearDay,
  type YearDayStatus,
} from '../utils/holidays'
import type { ConditionBadge } from '../utils/conditions'
import { EFFECT_LEGEND, MODE_LEGEND, effectLabel, effectSymbol, modeVisual } from '../utils/dailyStatusVisual'

export type YearDayOverride = {
  date: string
  is_working_capable: boolean
  reason?: string | null
}

export type PlanningDayStatus = {
  mode: string
  effects: { type: string; reason: string | null }[]
}

export type YearCalendarResult = {
  date: string
  is_working_capable: boolean
  reason: string
}[]

type Props = {
  /** 初始显示年份（内部可切换 ◀ ▶，非受控） */
  year: number
  editable?: boolean
  /** 已有版本内容回显（覆盖默认规则）；未覆盖日期按默认规则（周末+节假日） */
  overrides?: YearDayOverride[]
  /** 排产条件徽标：按日期索引，渲染在对应日格子上（位置可视化） */
  conditionByDate?: Record<string, ConditionBadge[]>
  /** Phase 3B：每日有效状态投影（生产模式 + Overlay），纯视觉映射 */
  planningStatusByDate?: Record<string, PlanningDayStatus>
  /** 年份切换或状态变更后触发（editable 下点击也触发） */
  onChange?: (year: number, result: YearCalendarResult) => void
  /** 仅用户点击日期切换时触发（用于父组件 DIRTY 语义） */
  onToggle?: () => void
  /** 允许拖拽框选日期段（贴条件模块入口）；非 editable 才生效 */
  onRangeSelect?: (start: string, end: string) => void
}

const MONTH_CN = ['一月', '二月', '三月', '四月', '五月', '六月', '七月', '八月', '九月', '十月', '十一月', '十二月']

/** 年度厂历（12 月网格）：周末+节假日=休息、调休班=生产；点击切换（编辑模式）。
 *  条件徽标（conditionByDate）渲染在日格底部；onRangeSelect 提供拖拽框选。 */
export function YearCalendar({
  year: initialYear,
  editable = false,
  overrides = [],
  conditionByDate = {},
  planningStatusByDate = {},
  onChange,
  onToggle,
  onRangeSelect,
}: Props) {
  const [year, setYear] = useState(initialYear)

  // base = 默认规则（周末+节假日）；override 合并已有版本内容
  const base = useMemo(() => {
    const map = new Map<string, { status: YearDayStatus; label: string }>()
    for (const d of defaultYearDays(year)) map.set(d.date, { status: d.status, label: d.label })
    for (const o of overrides) {
      if (o.date.startsWith(`${year}-`)) {
        map.set(o.date, { status: o.is_working_capable ? 'prod' : 'off', label: o.reason || '' })
      }
    }
    return map
  }, [year, overrides])

  const [days, setDays] = useState<YearDay[]>(() => defaultYearDays(year))

  useEffect(() => {
    const merged = defaultYearDays(year).map((d) => {
      const over = base.get(d.date)
      return over ? { ...d, status: over.status, label: over.label } : d
    })
    setDays(merged)
    // 初始化/年份切换/回显变化后上抛全量结果，父组件始终持有最新编辑内容
    onChange?.(
      year,
      merged.map((d) => ({ date: d.date, is_working_capable: d.status === 'prod', reason: d.label })),
    )
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [year, overrides])

  // drag range select (attach-condition entry)
  const [dragStart, setDragStart] = useState<string | null>(null)
  const [dragEnd, setDragEnd] = useState<string | null>(null)
  const draggingRef = useRef(false)

  const canRangeSelect = Boolean(onRangeSelect) && !editable

  const rangeContains = (date: string): boolean => {
    if (!dragStart || !dragEnd) return date === dragStart
    return date >= (dragStart < dragEnd ? dragStart : dragEnd) && date <= (dragStart > dragEnd ? dragStart : dragEnd)
  }

  const pointerDown = (date: string) => {
    if (!canRangeSelect) return
    draggingRef.current = true
    setDragStart(date)
    setDragEnd(date)
  }
  const pointerEnter = (date: string) => {
    if (!draggingRef.current) return
    setDragEnd(date)
  }
  const pointerUp = () => {
    if (!draggingRef.current) return
    draggingRef.current = false
    if (dragStart && dragEnd && dragStart !== dragEnd) {
      const start = dragStart < dragEnd ? dragStart : dragEnd
      const end = dragStart < dragEnd ? dragEnd : dragStart
      onRangeSelect?.(start, end)
    } else if (dragStart) {
      onRangeSelect?.(dragStart, dragStart)
    }
    setDragStart(null)
    setDragEnd(null)
  }

  const emit = (next: YearDay[]) => {
    setDays(next)
    onChange?.(
      year,
      next.map((d) => ({ date: d.date, is_working_capable: d.status === 'prod', reason: d.label })),
    )
  }

  const toggleDay = (date: string) => {
    if (!editable) return
    onToggle?.()
    emit(
      days.map((d) =>
        d.date === date ? { ...d, status: d.status === 'prod' ? 'off' : 'prod', label: '' } : d,
      ),
    )
  }

  const changeYear = (next: number) => {
    if (next < CALENDAR_YEAR_MIN || next > CALENDAR_YEAR_MAX) return
    setYear(next)
  }

  const prodCount = days.filter((d) => d.status === 'prod').length
  const basis = calendarBasis(year)
  const byMonth = (month: number) => days.filter((d) => Number(d.date.slice(5, 7)) === month)
  const leading = (month: number) => {
    const first = byMonth(month)[0]
    if (!first) return 0
    const dow = new Date(`${first.date}T00:00:00`).getDay()
    return (dow + 6) % 7 // 周一 = 0
  }

  return (
    <div className="year-calendar">
      <div className="cal-head">
        <div className="cal-year-row">
          <button type="button" onClick={() => changeYear(year - 1)} disabled={year <= CALENDAR_YEAR_MIN} aria-label="上一年">
            <LeftOutlined />
          </button>
          <span className="cal-year-label">{year}</span>
          <button type="button" onClick={() => changeYear(year + 1)} disabled={year >= CALENDAR_YEAR_MAX} aria-label="下一年">
            <RightOutlined />
          </button>
          <span className="cal-stats">生产日 {prodCount} · 休息日 {days.length - prodCount}</span>
        </div>
        {editable && <div className="cal-edit-hint">点击日期切换 工作日 / 休息日</div>}
        {basis === 'statutory-days-only' && (
          <div className="cal-future-hint">本年为法定日本日基础版；连休和调休待国务院年度通知公布后人工维护。</div>
        )}
        {canRangeSelect && <div className="cal-edit-hint">按住并拖动日期框选时间段，可快速贴条件模块</div>}
      </div>
      <div className="cal-grid">
        {MONTH_CN.map((name, idx) => {
          const month = idx + 1
          const lead = leading(month)
          const cells: ReactNode[] = []
          for (let i = 0; i < lead; i++) cells.push(<div key={`empty-${i}`} className="cal-cell empty" />)
          for (const d of byMonth(month)) {
            const ban = d.label === WORK_LABEL ? ' ban' : ''
            const badges = conditionByDate[d.date] ?? []
            const planning = planningStatusByDate[d.date]
            const visual = planning ? modeVisual(planning.mode) : null
            const showCalendarLabel = Boolean(d.label) && (d.status === 'off' || d.label === WORK_LABEL)
            const hasHiddenNote = Boolean(d.label) && d.status === 'prod' && d.label !== WORK_LABEL
            const selected = canRangeSelect && draggingRef.current && rangeContains(d.date)
            cells.push(
              <div key={d.date} className="cal-cell">
                <button
                  type="button"
                  className={`cal-day ${d.status}${ban}${editable ? ' editable' : ''}${canRangeSelect ? ' range-selectable' : ''}${selected ? ' range-selected' : ''}${visual ? ` ${visual.className}` : ''}`}
                  data-date={d.date}
                  title={`${d.date} ${d.wd}${visual ? ` · ${visual.label}` : ''}${d.label ? ` · ${d.label}` : ''}${planning?.effects?.length ? ` · ${planning.effects.map((e) => effectLabel(e.type)).join('/')}` : ''}`}
                  onClick={() => toggleDay(d.date)}
                  onPointerDown={() => pointerDown(d.date)}
                  onPointerEnter={() => pointerEnter(d.date)}
                  onPointerUp={pointerUp}
                  disabled={!editable && !canRangeSelect}
                >
                  <span className="cal-num">{Number(d.date.slice(8, 10))}</span>
                  {visual ? <span className="cal-planning-label">{visual.label}</span> : showCalendarLabel ? <span className="cal-label">{d.label}</span> : null}
                  {hasHiddenNote && <span className="cal-note-dot" title={d.label} aria-label="有备注" />}
                  {planning?.effects?.length ? (
                    <span className="cal-effects">
                      {planning.effects.slice(0, 2).map((effect) => (
                        <span key={effect.type} className="cal-effect-badge" title={`${effectLabel(effect.type)}${effect.reason ? `（${effect.reason}）` : ''}`}>
                          {effectSymbol(effect.type)}
                        </span>
                      ))}
                    </span>
                  ) : null}
                  {badges.length > 0 && (
                    <span className="cal-conditions">
                      {badges.slice(0, 2).map((badge) => (
                        <span key={badge.key} className={`cal-condition-dot ${badge.color}`} title={`${badge.label}（${badge.group}）`} />
                      ))}
                      {badges.length > 2 && <span className="cal-condition-more" title={badges.map((b) => b.label).join(' / ')}>+{badges.length - 2}</span>}
                    </span>
                  )}
                </button>
              </div>,
            )
          }
          return (
            <div key={month} className="cal-month">
              <h4>{name}</h4>
              <div className="cal-weeks">{cells}</div>
            </div>
          )
        })}
      </div>
      <div className="cal-legend">
        <span><i className="cal-swatch prod" />生产日</span>
        <span><i className="cal-swatch off" />休息日</span>
        <span className="cal-legend-holiday">节假日（红字）</span>
        <span className="cal-legend-ban">班（调休上班）</span>
        {MODE_LEGEND.map((item) => (
          <span key={item.mode}><i className="cal-swatch" style={{ background: item.color }} />{item.label}</span>
        ))}
        {EFFECT_LEGEND.map((item) => (
          <span key={item.type}><i className="cal-effect-badge">{item.symbol}</i>{item.label}</span>
        ))}
        {Object.keys(conditionByDate).length > 0 && (
          <>
            <span><i className="cal-condition-dot red" />HARD 条件</span>
            <span><i className="cal-condition-dot purple" />CAPABILITY</span>
            <span><i className="cal-condition-dot blue" />INTENT</span>
          </>
        )}
      </div>
    </div>
  )
}
