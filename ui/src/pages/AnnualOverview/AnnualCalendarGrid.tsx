import type { AnnualDay } from '../../api/core'
import { modeName, phaseName, quantity } from '../../api/core'
import { phaseBadge, phaseLabels } from '../../utils/corePhase'
export function AnnualCalendarGrid({ days, authModes, onSelectDate }: { days: AnnualDay[]; authModes: string[]; onSelectDate: (date: string) => void }) {
  const months = [...new Set(days.map(d => d.date.slice(0, 7)))].sort()
  return <>
    <div className="core-calendar-phase-legend" aria-label="阶段标签图例">
      <span>阶段标签：</span>
      {Object.entries(phaseLabels).map(([phase, label]) => <span className="core-calendar-phase-legend-item" key={phase}><span className={phaseBadge(phase)}>{label}</span>{phaseName(phase)}</span>)}
    </div>
    <div className="annual-calendar-grid">{months.map(month => {
    const dates = days.filter(d => d.date.startsWith(month))
    const leading = (new Date(dates[0].date + 'T00:00:00Z').getUTCDay() + 6) % 7
    return <div className="annual-calendar-month" key={month}>
      <div className="annual-calendar-month-title">{month.slice(0, 4)} 年 {Number(month.slice(5))} 月</div>
      <div className="annual-calendar-weekdays">{['一', '二', '三', '四', '五', '六', '日'].map(d => <span key={d}>{d}</span>)}</div>
      <div className="annual-calendar-days">{Array.from({ length: leading }, (_, i) => <span key={i} aria-hidden="true" />)}
        {dates.map(d => <button type="button" key={d.date} className="annual-calendar-day core-calendar-day" style={{ background: d.mode_summary === 'OFF' ? '#d8e1ee' : authModes.includes(d.mode_summary) ? '#7b3ff2' : '#1a8f5c', color: d.mode_summary === 'OFF' ? '#45536e' : '#fff' }} title={d.date + ' · ' + modeName(d.mode_summary) + ' · 完工 ' + quantity(d.fok) + ' 台'} onClick={() => onSelectDate(d.date)}>
          <span className="annual-calendar-day-num">{Number(d.date.slice(8))}</span><span className="annual-calendar-day-units">{quantity(d.fok)}</span>
          {d.phase.split('+').filter(phase => phase !== 'NORMAL').slice(0, 2).map(phase => <span key={phase} className={phaseBadge(phase)} title={phaseName(phase)}>{phaseLabels[phase]}</span>)}
          {!d.is_working_capable && d.mode_summary !== 'OFF' && <span className="core-saturday">加</span>}
        </button>)}
      </div>
    </div>
  })}</div></>
}
