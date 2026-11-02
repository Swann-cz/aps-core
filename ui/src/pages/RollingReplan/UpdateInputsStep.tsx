import { Alert, Button, Card, Space, Table, Tag, Upload, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/planning'
import type { SalesPlanVersion } from '../../types/api'
import type { ChangeSource } from './types'

export function UpdateInputsStep({
  source,
  actualRevisionId,
  onActualChange,
  salesPlanVersionId,
  onSalesChange,
  activeSales,
  inputGaps,
  inputFetching,
  inputError,
  onRetryInputs,
  blocked,
  onBack,
  onNext,
}: {
  source: ChangeSource
  actualRevisionId: string | null
  onActualChange: (id: string) => void
  salesPlanVersionId: string | null
  onSalesChange: (id: string) => void
  activeSales: SalesPlanVersion | undefined
  inputGaps: string[]
  inputFetching: boolean
  inputError: boolean
  onRetryInputs: () => void
  blocked: boolean
  onBack: () => void
  onNext: () => void
}) {
  const queryClient = useQueryClient()
  const needsActual = source === 'actual' || source === 'combined'
  const showsSales = source === 'sales' || source === 'combined'
  const revisionsQuery = useQuery({
    queryKey: ['actual-revisions'],
    queryFn: () => api.actualRevisions(),
    enabled: needsActual,
    retry: false,
  })
  const revisionsFetching = needsActual && revisionsQuery.isFetching
  const revisionsError = needsActual && (revisionsQuery.isError || revisionsQuery.isRefetchError)
  const authoritativeFetching = inputFetching || revisionsFetching
  const authoritativeError = inputError || revisionsError

  const importActual = useMutation({
    mutationFn: (file: File) => api.importActualRevision(file, new Date().toISOString().slice(0, 10), 'L1 新一轮'),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        const revisionId = result.actual_revision_id
          ?? (result.payload?.actual_revision_id as string | undefined)
        message.success('ActualRevision 已保存')
        void queryClient.invalidateQueries({ queryKey: ['actual-revisions'] })
        if (revisionId) onActualChange(revisionId)
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  return (
    <Card size="small" title="第 2 步 · 更新输入">
      {authoritativeFetching && <Alert type="info" showIcon message="正在刷新后端输入" style={{ marginBottom: 12 }} />}
      {!authoritativeFetching && authoritativeError && (
        <Alert
          type="error"
          showIcon
          message="后端输入查询失败"
          action={(
            <Button onClick={() => {
              onRetryInputs()
              if (needsActual) void revisionsQuery.refetch()
            }}>
              重试后端输入
            </Button>
          )}
          style={{ marginBottom: 12 }}
        />
      )}
      {!authoritativeFetching && !authoritativeError && inputGaps.length > 0 && (
        <Alert
          type="error"
          showIcon
          message="API Gap：缺少后端当前输入"
          description={inputGaps.join('、')}
          style={{ marginBottom: 12 }}
        />
      )}
      {needsActual && (
        <section>
          <h4>选择或导入实际产量修订</h4>
          {actualRevisionId ? (
            <div data-testid="selected-actual-revision" style={{ marginBottom: 8 }}>
              <Tag color="blue">已选择</Tag>
              <code>{actualRevisionId.slice(0, 8)}…</code>
            </div>
          ) : (
            <Alert type="warning" showIcon message="请选择或导入 ActualRevision" style={{ marginBottom: 8 }} />
          )}
          <Upload
            showUploadList={false}
            beforeUpload={(file) => {
              importActual.mutate(file)
              return false
            }}
          >
            <Button>导入实际产量 Excel</Button>
          </Upload>
          <Table
            size="small"
            style={{ marginTop: 10 }}
            rowKey="actual_revision_id"
            dataSource={revisionsQuery.data || []}
            pagination={false}
            columns={[
              { title: 'Revision', dataIndex: 'actual_revision_id', render: (v: string) => <code>{v.slice(0, 8)}…</code> },
              { title: '生效日期', dataIndex: 'effective_date' },
              {
                title: '选择',
                key: 'select',
                render: (_: unknown, record) => (
                  record.actual_revision_id === actualRevisionId
                    ? <Tag color="blue">当前选中</Tag>
                    : (
                      <Button size="small" onClick={() => onActualChange(record.actual_revision_id)}>
                        选择此修订
                      </Button>
                    )
                ),
              },
            ]}
          />
        </section>
      )}
      {showsSales && (
        <section>
          <h4>销售计划更新</h4>
          {activeSales && (
            <div style={{ marginBottom: 8 }}>
              <Tag>当前生效：{activeSales.display_name}</Tag>
              {salesPlanVersionId !== activeSales.sales_plan_version_id && (
                <Button size="small" style={{ marginLeft: 8 }} onClick={() => onSalesChange(activeSales.sales_plan_version_id)}>
                  使用此计划
                </Button>
              )}
            </div>
          )}
          <div className="muted">导入新销售计划后自动使用最新生效版本（可前往「销售数据」维护）。</div>
        </section>
      )}
      {source === 'conditions' && (
        <section>
          <h4>排产条件调整</h4>
          <div className="muted">条件变更在「排产条件」页维护；新一轮自动继承当前条件并允许本轮覆盖。</div>
        </section>
      )}
      {source === 'combined' && (
        <section>
          <h4>综合更新</h4>
          <div className="muted">依次处理：1) 实际产量修订 → 2) 销售计划版本 → 3) 排产条件调整。三个来源可同时变化。</div>
        </section>
      )}
      <Space style={{ marginTop: 14 }}>
        <Button onClick={onBack}>上一步：变化来源</Button>
        <Button
          type="primary"
          loading={authoritativeFetching}
          disabled={blocked || authoritativeError || inputGaps.length > 0 || !salesPlanVersionId || (needsActual && !actualRevisionId)}
          onClick={onNext}
        >
          下一步：影响范围
        </Button>
      </Space>
    </Card>
  )
}
