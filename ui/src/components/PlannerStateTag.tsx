import { Tag, Tooltip } from 'antd'

// Epic D: the frozen planner_state axis (BLOCKED > DECISION_REQUIRED >
// ATTENTION > READY). Backend-derived only; null means "no working
// planner_state" (lifecycle axis applies instead).
const PLANNER_STATE_META: Record<string, { color: string; label: string }> = {
  BLOCKED: { color: 'red', label: 'BLOCKED 阻断' },
  DECISION_REQUIRED: { color: 'gold', label: 'DECISION_REQUIRED 需决策' },
  ATTENTION: { color: 'orange', label: 'ATTENTION 需关注' },
  READY: { color: 'green', label: 'READY 可确认' },
}

export function PlannerStateTag({ value, fallback }: { value: string | null | undefined; fallback?: string | null }) {
  if (!value) {
    return (
      <Tooltip title="当前没有工作 planner_state（非 OPEN 会话或非 PROPOSED head）">
        <Tag color="default">{fallback ? `${fallback}（生命周期）` : '—'}</Tag>
      </Tooltip>
    )
  }
  const meta = PLANNER_STATE_META[value]
  if (!meta) return <Tag>{value}</Tag>
  return (
    <Tooltip title="后端派生的决策状态（不落库；BLOCKED > DECISION_REQUIRED > ATTENTION > READY）">
      <Tag color={meta.color}>{meta.label}</Tag>
    </Tooltip>
  )
}
