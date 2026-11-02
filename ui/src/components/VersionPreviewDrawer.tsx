import { Alert, Card, Descriptions, Drawer, Empty, Skeleton, Table, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { StatusTag } from './StatusTag'
import { SettingDetail, type SettingKind } from '../pages/MasterData/SettingReadOnlyDrawer'

export type VersionPreviewKind = 'sales' | 'pr' | 'ws' | 'factory' | 'calendar' | 'initial' | 'wip' | 'algorithm' | 'actual'

export function VersionPreviewDrawer({
  open,
  title,
  kind,
  queryKey,
  load,
  onClose,
}: {
  open: boolean
  title: string
  kind: VersionPreviewKind
  queryKey: readonly unknown[]
  load: (() => Promise<unknown>) | null
  onClose: () => void
}) {
  const query = useQuery({ queryKey, queryFn: load || (() => Promise.resolve(null)), enabled: open && Boolean(load), retry: false })
  const data = query.data as Record<string, unknown> | null | undefined
  const versionId = data ? String(
    data.sales_plan_version_id
    || data.pr_version_id
    || data.ws_version_id
    || data.factory_model_version_id
    || data.calendar_version_id
    || data.initial_state_snapshot_id
    || data.wip_target_version_id
    || data.actual_revision_id
    || data.profile_id
    || '—',
  ) : '—'
  return (
    <Drawer title={`只读预览 · ${title}`} open={open} onClose={onClose} width={640}>
      {query.isLoading ? <Skeleton active paragraph={{ rows: 9 }} /> : query.isError ? (
        <Alert type="error" showIcon message="版本详情读取失败" description={query.error instanceof Error ? query.error.message : String(query.error)} />
      ) : !data ? <Alert type="info" showIcon message="当前没有可预览的版本" /> : (
        <>
          <Descriptions size="small" bordered column={1} style={{ marginBottom: 16 }}>
            <Descriptions.Item label="显示名称">{String(data.display_name || data.profile_id || title)}</Descriptions.Item>
            {'business_id' in data && <Descriptions.Item label="业务 ID">{String(data.business_id || '—')}</Descriptions.Item>}
            {'status' in data && <Descriptions.Item label="状态"><StatusTag value={String(data.status || '—')} /></Descriptions.Item>}
            <Descriptions.Item label="版本 ID"><code>{versionId}</code></Descriptions.Item>
            {'created_at' in data && <Descriptions.Item label="创建时间">{String(data.created_at || '—')}</Descriptions.Item>}
            {'effective_date' in data && <Descriptions.Item label="生效日期">{String(data.effective_date || '—')}</Descriptions.Item>}
            <Descriptions.Item label="权限">只读；此处不提供修改、激活或保存操作</Descriptions.Item>
          </Descriptions>
          <Typography.Text type="secondary">以下内容直接复用基础设置和销售数据的业务预览样式。</Typography.Text>
          <div style={{ marginTop: 16 }}><BusinessVersionDetail kind={kind} detail={data} /></div>
        </>
      )}
    </Drawer>
  )
}

function BusinessVersionDetail({ kind, detail }: { kind: VersionPreviewKind; detail: Record<string, unknown> }) {
  if (['factory', 'calendar', 'initial', 'wip'].includes(kind)) {
    return <SettingDetail kind={kind as SettingKind} detail={detail} />
  }
  if (kind === 'sales') return <SalesVersionDetail months={(detail.months || []) as SalesFact[]} />
  if (kind === 'pr' || kind === 'ws') return <DemandVersionDetail kind={kind} months={(detail.months || []) as DemandFact[]} />
  if (kind === 'algorithm') return <AlgorithmProfileDetail profile={detail} />
  if (kind === 'actual') return <ActualRevisionDetail entries={(detail.entries || []) as Record<string, unknown>[]} />
  return <Alert type="info" showIcon message="当前版本没有可展示的业务明细" />
}

type SalesFact = { month: string; typeclass_id: string; pr: number | null; ws: number | null }

function SalesVersionDetail({ months }: { months: SalesFact[] }) {
  if (!months.length) return <Empty description="该销售版本没有月度数据" />
  return <Card size="small" title="销售计划 · 月份 × 车型">
    <Table size="small" bordered pagination={{ pageSize: 24 }} rowKey={(row) => `${row.month}-${row.typeclass_id}`} dataSource={months} columns={[
      { title: '月份', dataIndex: 'month', width: 110 },
      { title: '车型', dataIndex: 'typeclass_id', width: 90 },
      { title: 'PR', dataIndex: 'pr', align: 'right' as const, render: (value) => value ?? '—' },
      { title: 'WS', dataIndex: 'ws', align: 'right' as const, render: (value) => value ?? '—' },
    ]} />
  </Card>
}

type DemandFact = { month: string; typeclass_id: string; quantity: number }

function DemandVersionDetail({ kind, months }: { kind: 'pr' | 'ws'; months: DemandFact[] }) {
  if (!months.length) return <Empty description={`该 ${kind.toUpperCase()} 版本没有月度数据`} />
  const monthKeys = Array.from(new Set(months.map((item) => item.month))).sort()
  const year = monthKeys[0]?.slice(0, 4) || String(new Date().getFullYear())
  const allMonths = Array.from({ length: 12 }, (_, index) => `${year}-${String(index + 1).padStart(2, '0')}`)
  const typeclasses = Array.from(new Set(months.map((item) => item.typeclass_id))).sort()
  const rows = [...allMonths.map((month) => ({ key: month, month, total: false })), { key: 'TTL', month: 'TTL.', total: true }]
  return <Card size="small" title={`${kind.toUpperCase()} · 全年月度纵向预览`} extra={<Tag color={monthKeys.length === 12 ? 'success' : 'warning'}>覆盖 {monthKeys.length} / 12 个月</Tag>}>
    <Table size="small" bordered pagination={false} rowKey="key" scroll={{ x: 560 }} dataSource={rows} rowClassName={(row) => row.total ? 'v6-demand-total-row' : ''} columns={[
      { title: '月份', dataIndex: 'month', fixed: 'left', width: 110, render: (value, row) => row.total ? <strong>{value}</strong> : value },
      ...typeclasses.map((typeclass) => ({
        title: `车型 ${typeclass}`,
        width: 120,
        align: 'right' as const,
        render: (_: unknown, row: { month: string; total: boolean }) => {
          if (row.total) return <strong>{months.filter((item) => item.typeclass_id === typeclass).reduce((sum, item) => sum + item.quantity, 0)}</strong>
          return months.find((item) => item.month === row.month && item.typeclass_id === typeclass)?.quantity ?? '—'
        },
      })),
      { title: '月合计', fixed: 'right' as const, width: 120, align: 'right' as const, render: (_: unknown, row: { month: string; total: boolean }) => {
        const facts = row.total ? months : months.filter((item) => item.month === row.month)
        if (!row.total && facts.length === 0) return '—'
        return <strong>{facts.reduce((sum, item) => sum + item.quantity, 0)}</strong>
      } },
    ]} />
  </Card>
}

const ALGORITHM_LABELS: Record<string, string> = {
  inventory_policy: '库存策略',
  monthly_pp_allocation: '月度 PP 分配',
  working_mode_selection: '工作模式选择',
  block_placement: '生产块排布',
  welding_sequence: '焊装顺序',
  candidate_selection: '候选选择',
}

function AlgorithmProfileDetail({ profile }: { profile: Record<string, unknown> }) {
  const rows = Object.keys(ALGORITHM_LABELS).map((slot) => ({ slot, ...(profile[slot] as Record<string, unknown> || {}) }))
  return <Card size="small" title="六算法槽配置"><Table size="small" pagination={false} rowKey="slot" dataSource={rows} columns={[
    { title: '职责', dataIndex: 'slot', render: (value) => ALGORITHM_LABELS[String(value)] },
    { title: '算法', dataIndex: 'display_name', render: (value: unknown, row: any) => String(value || row.algorithm_id || '—') },
    { title: '版本', dataIndex: 'version', render: (value) => String(value || '—') },
  ]} /></Card>
}

function ActualRevisionDetail({ entries }: { entries: Record<string, unknown>[] }) {
  if (!entries.length) return <Empty description="该 Actual Revision 没有事实明细" />
  const keys = Array.from(new Set(entries.flatMap((item) => Object.keys(item))))
  return <Card size="small" title="Actual 事实"><Table size="small" pagination={{ pageSize: 12 }} rowKey={(_row, index) => String(index)} dataSource={entries} columns={keys.map((key) => ({ title: key, dataIndex: key, render: (value: unknown) => typeof value === 'object' ? JSON.stringify(value) : String(value ?? '—') }))} /></Card>
}
