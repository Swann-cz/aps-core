import { useState } from 'react'
import { Button, Space, Table, message } from 'antd'
import { EyeOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { StatusTag } from '../../components/StatusTag'
import { VersionPreviewDrawer } from '../../components/VersionPreviewDrawer'

export function SalesHistory() {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [detailId, setDetailId] = useState<string | null>(null)
  const versionsQuery = useQuery({
    queryKey: ['sales-plan-versions'],
    queryFn: () => api.salesPlanVersions(),
  })
  const activateMutation = useMutation({
    mutationFn: (versionId: string) => api.activateSalesPlanVersion(versionId),
    onSuccess: (result) => {
      if (result.outcome === 'ACTIVATED') {
        message.success('已激活为当前销售计划')
        queryClient.invalidateQueries({ queryKey: ['sales-plan-versions'] })
        queryClient.invalidateQueries({ queryKey: ['v6', 'pr'] })
        queryClient.invalidateQueries({ queryKey: ['v6', 'ws'] })
      } else {
        message.error(`激活失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('激活失败'),
  })

  if (versionsQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (versionsQuery.error)
    return <PageState kind="system-error" error={versionsQuery.error} onRetry={() => window.location.reload()} />

  return (
    <div className="page-container">
      <PageHeader
        title="销售计划 · 版本历史"
        subtitle="全部版本与 supersedes 链；激活为单激活规则"
        actions={<Button onClick={() => navigate('/sales')}>返回当前生效计划</Button>}
      />
      <Table
        size="small" bordered rowKey="sales_plan_version_id"
        dataSource={versionsQuery.data || []}
        pagination={{ pageSize: 10 }}
        columns={[
          { title: '显示名称', dataIndex: 'display_name' },
          { title: '状态', dataIndex: 'status', width: 160, render: (v: string) => <StatusTag value={v} /> },
          {
            title: '操作',
            key: 'action',
            width: 210,
            render: (_: unknown, record: any) => (
              <Space size={4}>
                <Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(record.sales_plan_version_id)}>查看详情</Button>
                {record.status !== 'ACTIVE' && (
                  <Button
                    size="small"
                    type="primary"
                    ghost
                    loading={activateMutation.isPending}
                    onClick={() => activateMutation.mutate(record.sales_plan_version_id)}
                  >
                    激活
                  </Button>
                )}
                {record.status === 'ACTIVE' && <span className="muted">当前生效</span>}
              </Space>
            ),
          },
        ]}
      />
      <VersionPreviewDrawer
        open={Boolean(detailId)}
        title="销售计划版本"
        kind="sales"
        queryKey={['sales-plan-version-detail', detailId]}
        load={detailId ? () => api.salesPlanVersionDetail(detailId) : null}
        onClose={() => setDetailId(null)}
      />
    </div>
  )
}
