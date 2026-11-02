import type { ScenarioSummary, SuggestView } from '../../api/core'

// 步骤编号与契约一致；只从当前服务端状态推导，不持久化进度。
export function wizardStep(scenario: ScenarioSummary | undefined, suggest: SuggestView | undefined) {
  if (!scenario) return 0
  if (scenario.formal) return 6
  if (scenario.run.state === 'RUNNING' || scenario.state === 'RUNNING') return 3
  if (scenario.state === 'FAILED' || (scenario.state === 'READY' && scenario.no_plan)) return 3
  if (scenario.state === 'NO_PLAN' || scenario.state === 'STALE') return 2
  if (suggest?.stage === 'NO_GAP') return 5
  if (suggest && ['HAS_GAP', 'CANDIDATES_PENDING', 'CANDIDATES_DONE', 'EXHAUSTED'].includes(suggest.stage)) return 4
  return 3
}
