import { useState } from 'react'
import { Button, Card, Space } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { PageState } from '../../components/PageState'
import { StatusTag } from '../../components/StatusTag'
import { SalesImportDrawer } from '../Sales/SalesImportDrawer'
import type { StartPlanningDraft } from './types'

export function SalesPlanStep({
  draft,
  onChange,
  onNext,
}: {
  draft: StartPlanningDraft
  onChange: (draft: StartPlanningDraft) => void
  onNext: () => void
}) {
  const [importOpen, setImportOpen] = useState(false)
  const versionsQuery = useQuery({
    queryKey: ['sales-plan-versions'],
    queryFn: () => api.salesPlanVersions(),
  })
  const active = (versionsQuery.data || []).find((v) => v.status === 'ACTIVE')

  if (versionsQuery.isLoading) return <PageState kind="loading" rows={4} />
  if (versionsQuery.error)
    return <PageState kind="system-error" error={versionsQuery.error} onRetry={() => window.location.reload()} />

  const selected = draft.salesPlanVersionId
  return (
    <Card size="small" title="第 1 步 · 销售计划">
      {active ? (
        <div className="sales-plan-choice">
          <div>
            <strong>当前生效计划</strong>
            <span className="muted" style={{ marginLeft: 8 }}>
              {active.display_name}
            </span>
            <StatusTag value={active.status} />
          </div>
          <Space style={{ marginTop: 12 }}>
            <Button
              type="primary"
              disabled={selected === active.sales_plan_version_id}
              onClick={() => onChange({ ...draft, salesPlanVersionId: active.sales_plan_version_id })}
            >
              使用此计划
            </Button>
            <Button onClick={() => setImportOpen(true)}>导入新计划</Button>
            <Button
              disabled={!selected}
              onClick={onNext}
            >
              下一步：排产条件
            </Button>
          </Space>
          {!selected && <div className="muted" style={{ marginTop: 8 }}>选择或导入销售计划后继续</div>}
        </div>
      ) : (
        <PageState
          kind="business-blocked"
          title="缺少销售计划"
          reasons={['还没有生效的销售计划版本']}
          action={<Button onClick={() => setImportOpen(true)}>导入新计划</Button>}
        />
      )}
      <SalesImportDrawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSaved={(versionId) => onChange({ ...draft, salesPlanVersionId: versionId })}
      />
    </Card>
  )
}
