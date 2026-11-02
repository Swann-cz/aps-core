import { useState } from 'react'
import { PageHeader } from '../../components/PageHeader'
import { StartPlanningShell } from './StartPlanningShell'
import { SalesPlanStep } from './SalesPlanStep'
import { PlanningConditionsStep } from './PlanningConditionsStep'
import { PreflightGenerateStep } from './PreflightGenerateStep'
import { GenerationComplete } from './GenerationComplete'
import { createStartDraft, type StartPlanningDraft, type StartTask } from './types'

export function P00Setup() {
  const [task, setTask] = useState<StartTask>('sales')
  const [draft, setDraft] = useState<StartPlanningDraft>(() => createStartDraft())
  const [complete, setComplete] = useState<{
    planVersionId: string | null
    annualClosure?: number | null
    productionDays?: number | null
    issueCount: number
  } | null>(null)

  if (complete) {
    return (
      <div>
        <PageHeader title="发起排产" subtitle="正常年度排产向导" />
        <GenerationComplete
          planVersionId={complete.planVersionId}
          annualClosure={complete.annualClosure}
          productionDays={complete.productionDays}
          issueCount={complete.issueCount}
          onOpenAnnual={() => (window.location.href = '/v5/annual-overview')}
          onOpenIssues={() => (window.location.href = '/issues')}
        />
      </div>
    )
  }

  return (
    <div>
      <PageHeader title="发起排产" subtitle="正常年度排产：三个操作任务" />
      <StartPlanningShell
        task={task}
        salesPlanSelected={Boolean(draft.salesPlanVersionId)}
        onSelect={setTask}
      >
        {task === 'sales' && (
          <SalesPlanStep
            draft={draft}
            onChange={setDraft}
            onNext={() => setTask('conditions')}
          />
        )}
        {task === 'conditions' && (
          <PlanningConditionsStep
            draft={draft}
            onChange={setDraft}
            onNext={() => setTask('preflight')}
            onBack={() => setTask('sales')}
          />
        )}
        {task === 'preflight' && (
          <PreflightGenerateStep
            draft={draft}
            onBack={() => setTask('conditions')}
            onComplete={(result) =>
              setComplete({
                planVersionId: result.planVersionId,
                issueCount: result.issueCount,
              })
            }
          />
        )}
      </StartPlanningShell>
    </div>
  )
}
