import { useState } from 'react'
import { Alert, Button, Card, Empty, Segmented, Space, Table, Tag } from 'antd'
import { HistoryOutlined, ImportOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { StatusTag } from '../../components/StatusTag'
import { SalesImportDrawer } from './SalesImportDrawer'
import { SalesTemplateDownloadButton } from './SalesTemplateDownloadButton'

type MonthFact = { month: string; typeclass_id: string; pr: number | null; ws: number | null }
type DisplayMode = 'PR + WS' | 'PR' | 'WS'

export function Sales() {
  const navigate = useNavigate()
  const [importOpen, setImportOpen] = useState(false)
  const [mode, setMode] = useState<DisplayMode>('PR + WS')

  const versionsQuery = useQuery({
    queryKey: ['sales-plan-versions'],
    queryFn: () => api.salesPlanVersions(),
    staleTime: 30_000,
  })
  const active = (versionsQuery.data || []).find((v) => v.status === 'ACTIVE')
  const detailQuery = useQuery({
    queryKey: ['sales-plan-version-detail', active?.sales_plan_version_id],
    queryFn: () => api.salesPlanVersionDetail(active!.sales_plan_version_id),
    enabled: Boolean(active),
    staleTime: 30_000,
  })

  if (versionsQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (versionsQuery.error)
    return <PageState kind="system-error" error={versionsQuery.error} onRetry={() => window.location.reload()} />
  if (!active) {
    return (
      <div>
        <PageHeader
          title="销售数据"
          subtitle="当前没有生效销售计划"
          actions={
            <Space>
              <SalesTemplateDownloadButton />
              <Button icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
                导入新计划
              </Button>
              <Button icon={<HistoryOutlined />} onClick={() => navigate('/sales/history')}>
                查看历史
              </Button>
            </Space>
          }
        />
        <PageState kind="empty" title="尚未建立生效销售计划" />
        <SalesImportDrawer open={importOpen} onClose={() => setImportOpen(false)} onSaved={() => undefined} />
      </div>
    )
  }

  const detail = detailQuery.data
  const months: MonthFact[] = (detail?.months || []).map((m: any) => ({
    month: m.month,
    typeclass_id: m.typeclass_id,
    pr: m.pr ?? null,
    ws: m.ws ?? null,
  }))
  const monthKeys = Array.from(new Set(months.map((m) => m.month))).sort()
  const typeclasses = Array.from(new Set(months.map((m) => m.typeclass_id))).sort()
  const year = monthKeys.length ? Number(monthKeys[0].slice(0, 4)) : null
  const all12 = Array.from({ length: 12 }, (_, i) => (year ? `${year}-${String(i + 1).padStart(2, '0')}` : ''))
  const covered = all12.filter((m) => monthKeys.includes(m)).length

  return (
    <div className="page-container">
      <PageHeader
        title="销售数据"
        subtitle="PR / WS 按 月份 × 车型类别；每次保存 = 新不可变版本"
        actions={
          <Space>
            <SalesTemplateDownloadButton />
            <Button icon={<HistoryOutlined />} onClick={() => navigate('/sales/history')}>查看历史</Button>
            <Button type="primary" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
              导入新计划
            </Button>
          </Space>
        }
      />

      <Alert
        type="info"
        showIcon
        message="销售版本与 PR / WS"
        description="每次保存销售数据都会形成一个不可变销售版本，并生成同源的 PR 与 WS 输入。PR / WS 业务 ID 中 SALES 后缀相同，表示来自同一个销售版本。"
        style={{ marginBottom: 12 }}
      />

      <Card
        size="small"
        title={
          <Space>
            <span>当前生效销售计划</span>
            <StatusTag value={active.status} />
            <Tag>{covered} / 12</Tag>
          </Space>
        }
        extra={
          <Space>
            <span className="muted">{detail?.display_name}</span>
            <Segmented
              value={mode}
              onChange={(value) => setMode(value as DisplayMode)}
              options={['PR + WS', 'PR', 'WS']}
            />
          </Space>
        }
      >
        {detailQuery.isLoading ? (
          <PageState kind="loading" rows={4} />
        ) : months.length === 0 ? (
          <Empty description="该版本暂无月度数据 — 使用「导入新计划」" />
        ) : (
          <Table
            size="small" bordered rowKey="typeclass_id"
            dataSource={typeclasses.map((tc) => ({ typeclass_id: tc }))}
            pagination={false}
            scroll={{ x: 90 + monthKeys.length * 100 }}
            columns={[
              { title: '车型类别', dataIndex: 'typeclass_id', width: 90, fixed: 'left' },
              ...monthKeys.map((month) => ({
                title: month,
                key: month,
                width: 100,
                align: 'center' as const,
                render: (_: unknown, row: { typeclass_id: string }) => {
                  const fact = months.find((m) => m.month === month && m.typeclass_id === row.typeclass_id)
                  if (!fact) return <span style={{ color: '#b6c0d0' }}>—</span>
                  if (mode === 'PR') return <span>{fact.pr ?? '—'}</span>
                  if (mode === 'WS') return <span>{fact.ws ?? '—'}</span>
                  return <span>{fact.pr ?? '—'} / {fact.ws ?? '—'}</span>
                },
              })),
            ]}
          />
        )}
      </Card>

      <SalesImportDrawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSaved={() => {
          setImportOpen(false)
        }}
      />
    </div>
  )
}
