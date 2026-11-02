import { Select, Space, Tag } from 'antd'
import type { ScenarioSummary } from '../api/core'
import { useCore } from '../app/CoreContext'

// 方案下拉：完整名称 + 一眼能读的状态（UI_CONTRACT §10.7）
export function scenarioBadge(s: ScenarioSummary): { text: string; color?: string } {
  if (s.formal) return { text: '正式版', color: 'blue' }
  if (s.state === 'RUNNING' || s.run.state === 'RUNNING') return { text: '排产中', color: 'processing' }
  if (s.state === 'NO_PLAN') return { text: '未运行' }
  if (s.state === 'FAILED' || s.no_plan) return { text: '没排出', color: 'red' }
  if (s.state === 'STALE') return { text: '条件已改', color: 'orange' }
  if (s.verdict === 'REJECT') return { text: '未通过校验', color: 'red' }
  return { text: '已排出', color: 'green' }
}
export function ScenarioPicker({ width = 380 }: { width?: number }) {
  const state = useCore()
  const sorted = [...state.scenarios].sort((a, b) => b.created_at.localeCompare(a.created_at))
  return <Select aria-label="选择方案" style={{ width, maxWidth: '100%' }} popupMatchSelectWidth={false} showSearch optionFilterProp="name"
    loading={state.list.isLoading} value={state.scenario?.id} onChange={state.select} placeholder="暂无方案"
    options={sorted.map(s => { const badge = scenarioBadge(s); return { value: s.id, name: s.name, label: <Space size={6}><span title={s.name}>{s.name}</span><Tag color={badge.color} style={{ marginInlineEnd: 0 }}>{badge.text}</Tag></Space> } })} />
}
