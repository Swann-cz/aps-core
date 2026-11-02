import { Button, Steps } from 'antd'
import type { ReactNode } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { PageState } from '../../components/PageState'
import type { StartTask } from './types'

const TASK_ORDER: StartTask[] = ['sales', 'conditions', 'preflight']
const TASK_TITLES: Record<StartTask, string> = {
  sales: '销售计划',
  conditions: '排产条件',
  preflight: '检查生成',
}

function useBaseSettingsStatus() {
  const factory = useQuery({ queryKey: ['factory-model-versions'], queryFn: () => api.factoryModelVersions() })
  const calendar = useQuery({ queryKey: ['calendar-versions'], queryFn: () => api.calendarVersions() })
  const wip = useQuery({ queryKey: ['wip-target-versions'], queryFn: () => api.wipTargetVersions() })
  const initial = useQuery({ queryKey: ['initial-state-snapshots'], queryFn: () => api.initialStateSnapshots() })
  const queries = [factory, calendar, wip, initial]
  const ready = [
    (factory.data || []).some((v: any) => v.status === 'ACTIVE'),
    (calendar.data || []).some((v: any) => v.status === 'ACTIVE'),
    (wip.data || []).some((v: any) => v.status === 'ACTIVE'),
    (initial.data || []).some((v: any) => v.status === 'ACTIVE'),
  ]
  return {
    readyCount: ready.filter(Boolean).length,
    loading: queries.some((query) => query.isLoading),
    error: queries.find((query) => query.error)?.error,
  }
}

export function StartPlanningShell({
  task,
  salesPlanSelected,
  onSelect,
  children,
}: {
  task: StartTask
  salesPlanSelected: boolean
  onSelect: (task: StartTask) => void
  children: ReactNode
}) {
  const { readyCount, loading, error } = useBaseSettingsStatus()
  const baseSettingsReady = readyCount === 4
  const current = TASK_ORDER.indexOf(task)
  return (
    <div className="start-planning-layout">
      <div className="start-planning-ready">
        基础设置：{readyCount} 项已生效
      </div>
      <div className="start-planning-body">
        <aside className="start-task-rail" data-testid="start-task-rail">
          <Steps
            direction="vertical"
            size="small"
            current={current}
            items={TASK_ORDER.map((key) => {
              const disabled = !baseSettingsReady || (key !== 'sales' && !salesPlanSelected)
              return {
                title: TASK_TITLES[key],
                disabled,
                onClick: disabled ? undefined : () => onSelect(key),
              }
            })}
          />
        </aside>
        <main className="start-task-content">
          {loading ? (
            <PageState kind="loading" rows={4} />
          ) : error ? (
            <PageState kind="system-error" error={error} onRetry={() => window.location.reload()} />
          ) : !baseSettingsReady ? (
            <PageState
              kind="business-blocked"
              title="基础设置未就绪"
              reasons={[`当前仅 ${readyCount} / 4 项生效，必须先完成工厂模型、企业日历、WIP 目标和初始状态`]}
              action={<Button type="primary" onClick={() => (window.location.href = '/master-data')}>前往基础设置</Button>}
            />
          ) : children}
        </main>
      </div>
    </div>
  )
}
