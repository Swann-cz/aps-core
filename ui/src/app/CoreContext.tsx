import { createContext, useContext, useEffect, useState, type ReactNode } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { App } from 'antd'
import { core, type ScenarioSummary } from '../api/core'
function useCoreState() {
  const { message } = App.useApp()
  const client = useQueryClient()
  const [selectedId, setSelectedId] = useState(() => {
    try { return localStorage.getItem('aps-core-scenario') ?? '' } catch { return '' }
  })
  const list = useQuery({ queryKey: ['core', 'scenarios'], queryFn: core.scenarios, refetchInterval: query => query.state.data?.some(s => s.state === 'RUNNING') ? 3000 : false })
  const scenarios = list.data ?? []
  const scenario = scenarios.find(s => s.id === selectedId) ?? scenarios[0]
  useEffect(() => {
    if (!scenario) return
    try { localStorage.setItem('aps-core-scenario', scenario.id) } catch { /* 本地存储不可用时仍可选择方案。 */ }
  }, [scenario?.id])
  const update = (summary: ScenarioSummary) => {
    client.setQueryData<ScenarioSummary[]>(['core', 'scenarios'], old => {
      const items = old ?? []
      return items.some(s => s.id === summary.id) ? items.map(s => s.id === summary.id ? summary : s) : [summary, ...items]
    })
  }
  const run = useMutation({ mutationFn: core.run, onSuccess: update, onError: (error: Error) => { void message.error(error.message) } })
  return { scenarios, scenario, list, select: setSelectedId, update, run, busy: scenarios.some(s => s.state === 'RUNNING') }
}
const CoreContext = createContext<ReturnType<typeof useCoreState> | null>(null)
export function CoreProvider({ children }: { children: ReactNode }) { return <CoreContext.Provider value={useCoreState()}>{children}</CoreContext.Provider> }
export function useCore() { return useContext(CoreContext)! }
// 运行结束后使用新的查询键重新取视图，运行期间仍保留上次计划。
export const viewRevision = (scenario: ScenarioSummary | undefined) => [scenario?.run.finished_at, scenario?.state === 'RUNNING' ? 'running' : scenario?.state]
