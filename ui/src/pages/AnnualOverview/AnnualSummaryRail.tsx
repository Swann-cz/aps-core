import { quantity, type AnnualView } from '../../api/core'
export function AnnualSummaryRail({ totals }: { totals: AnnualView['totals'] }) {
  return <div className="annual-summary-rail">{([
    ['年度需求（台）', totals.annual_pr], ['年度完工（台）', totals.annual_fok], ['年度缺口（台）', totals.annual_gap],
    ['生产天数', totals.production_days], ['周六生产天数', totals.saturday_days], ['加班天数', totals.overtime_days],
  ] as const).map(([label, value]) => <div className="annual-summary-item" key={label}><span className="annual-summary-label">{label}</span><strong>{quantity(value)}</strong></div>)}</div>
}
