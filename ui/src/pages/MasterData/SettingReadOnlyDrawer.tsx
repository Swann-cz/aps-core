import { Alert, Card, Descriptions, Drawer, Spin, Table } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { StatusTag } from '../../components/StatusTag'
import { YearCalendar } from '../../components/YearCalendar'
import type { InitialStatePayload, WipTargetItem } from '../../types/api'

export type SettingKind = 'factory' | 'calendar' | 'wip' | 'initial'

export const SETTING_META: Record<SettingKind, { title: string; editRoute: string }> = {
  factory: { title: '工厂与产能模型', editRoute: '/master-data/factory/edit' },
  calendar: { title: '企业日历', editRoute: '/master-data/calendar/edit' },
  wip: { title: 'WIP 目标水位', editRoute: '/master-data/wip-target/edit' },
  initial: { title: '初始库存与在制', editRoute: '/master-data/initial-state/edit' },
}

const ID_FIELD: Record<SettingKind, string> = {
  factory: 'factory_model_version_id',
  calendar: 'calendar_version_id',
  wip: 'wip_target_version_id',
  initial: 'initial_state_snapshot_id',
}

function readDetail(kind: SettingKind, id: string) {
  if (kind === 'factory') return api.factoryModelVersionDetail(id)
  if (kind === 'calendar') return api.calendarVersionDetail(id)
  if (kind === 'wip') return api.wipTargetVersionDetail(id)
  return api.initialStateSnapshotDetail(id)
}

export function SettingReadOnlyDrawer({
  kind,
  record,
  onClose,
}: {
  kind: SettingKind
  record: any | undefined
  onClose: () => void
}) {
  const id = record ? String(record[ID_FIELD[kind]] || '') : ''
  const detailQuery = useQuery({
    queryKey: ['base-setting-readonly-detail', kind, id],
    queryFn: () => readDetail(kind, id),
    enabled: Boolean(id),
  })

  return (
    <Drawer
      className="setting-readonly-drawer"
      data-testid="base-setting-readonly-drawer"
      title={`${SETTING_META[kind].title}（只读）`}
      placement="right"
      width="50vw"
      open
      onClose={onClose}
    >
      {!record ? (
        <Alert type="warning" showIcon message="尚未配置生效版本" />
      ) : (
        <>
          <Descriptions column={1} size="small" bordered className="setting-readonly-meta">
            <Descriptions.Item label="显示名称">{record.display_name}</Descriptions.Item>
            <Descriptions.Item label="状态"><StatusTag value={record.status} /></Descriptions.Item>
            {record.created_at ? <Descriptions.Item label="创建时间">{record.created_at}</Descriptions.Item> : null}
            <Descriptions.Item label="版本 ID"><code>{id}</code></Descriptions.Item>
            <Descriptions.Item label="权限">只读；此处不提供修改或保存操作</Descriptions.Item>
          </Descriptions>
          {detailQuery.isLoading ? (
            <div className="setting-readonly-loading"><Spin tip="正在读取版本详情" /></div>
          ) : detailQuery.error ? (
            <Alert
              type="error"
              showIcon
              message="版本详情读取失败"
              description={detailQuery.error instanceof Error ? detailQuery.error.message : String(detailQuery.error)}
            />
          ) : (
            <SettingDetail kind={kind} detail={detailQuery.data} />
          )}
        </>
      )}
    </Drawer>
  )
}

export function SettingDetail({ kind, detail }: { kind: SettingKind; detail: any }) {
  if (kind === 'factory') return <FactoryDetail model={detail?.factory_model || {}} />
  if (kind === 'calendar') return <CalendarDetail days={detail?.days || []} />
  if (kind === 'wip') return <WipDetail targets={detail?.targets || []} />
  return <InitialStateDetail state={detail?.initial_state} />
}

const readonlyTableProps = {
  size: 'small' as const,
  pagination: false as const,
}

function FactoryDetail({ model }: { model: Record<string, any> }) {
  return (
    <div className="setting-readonly-sections">
      <Card size="small" title="车间（Workshops）">
        <Table {...readonlyTableProps} rowKey="workshop_id" dataSource={model.workshops || []} columns={[
          { title: '车间', dataIndex: 'workshop_id' },
          { title: '额定 JPH', dataIndex: 'nominal_jph' },
        ]} />
      </Card>
      <Card size="small" title="工作模式（Working Modes）">
        <Table {...readonlyTableProps} rowKey="working_mode_id" dataSource={model.working_modes || []} columns={[
          { title: '模式', dataIndex: 'working_mode_id' },
          { title: '计划工时', dataIndex: 'planned_hours' },
          { title: '班次数', dataIndex: 'shift_count', render: (value: number | null) => value ?? 1 },
        ]} />
      </Card>
      <Card size="small" title="缓冲（Buffers）">
        <Table {...readonlyTableProps} rowKey="buffer_id" dataSource={model.buffers || []} columns={[
          { title: '缓冲', dataIndex: 'buffer_id' },
          { title: '物理最大 WIP', dataIndex: 'physical_max_wip' },
        ]} />
      </Card>
      <Card size="small" title="车型绑定（Typeclasses）">
        <Table {...readonlyTableProps} rowKey="typeclass_id" dataSource={model.typeclasses || []} columns={[
          { title: '车型', dataIndex: 'typeclass_id' },
          { title: '车间', dataIndex: 'workshop_id' },
          { title: '胶龄上限（天）', dataIndex: 'glue_limit_calendar_days', render: (value: number | null) => value ?? '—' },
        ]} />
      </Card>
      <Alert
        type="info"
        showIcon
        message="胶龄上限使用规则"
        description="清线判断优先使用车型级胶龄上限；车型没有单独设置时，才使用缺省胶龄上限。停线自然日数达到或超过有效胶龄上限时，系统进入清线判断。"
      />
      <Card size="small" title="流边（Flow Edges）">
        <Table {...readonlyTableProps} rowKey={(row: any) => `${row.from_node}-${row.to_node}`} dataSource={model.flow_edges || []} columns={[
          { title: 'From', dataIndex: 'from_node' },
          { title: 'To', dataIndex: 'to_node' },
          { title: '当日流转', dataIndex: 'same_day_transfer', render: (value: boolean) => value ? '是' : '否' },
        ]} />
      </Card>
      <Card size="small" title="共享限制（Shared Limits）">
        <Table {...readonlyTableProps} rowKey="limit" dataSource={[
          { limit: 'BS1+BS2 共享焊接 JPH 上限', value: model.shared_welding_ceiling_jph },
          { limit: '缺省胶龄上限（天）', value: model.glue_limit_calendar_days },
        ]} columns={[
          { title: '限制', dataIndex: 'limit' },
          { title: '值', dataIndex: 'value', render: (value: number | null) => value ?? '—' },
        ]} />
      </Card>
    </div>
  )
}

function CalendarDetail({ days }: { days: { date: string; is_working_capable: boolean; reason?: string | null }[] }) {
  const firstYear = days[0]?.date ? Number(String(days[0].date).slice(0, 4)) : new Date().getFullYear()
  return (
    <Card size="small" title="全年工作日 / 休息日" className="setting-readonly-calendar">
      <YearCalendar year={firstYear} overrides={days} />
    </Card>
  )
}

function WipDetail({ targets }: { targets: WipTargetItem[] }) {
  return (
    <Card size="small" title="节点目标 WIP" className="setting-readonly-single-card">
      <Table {...readonlyTableProps} rowKey={(row) => `${row.node_type}-${row.node_id}`} dataSource={targets} columns={[
        { title: '节点', dataIndex: 'node_id' },
        { title: '类型', dataIndex: 'node_type' },
        { title: '目标 WIP', dataIndex: 'target_quantity' },
      ]} />
    </Card>
  )
}

type QuantityRow = { typeclass_id: string; quantity: number }

function QuantityTable({ title, rows }: { title: string; rows: QuantityRow[] }) {
  return (
    <Card size="small" title={title}>
      <Table {...readonlyTableProps} rowKey="typeclass_id" dataSource={rows} columns={[
        { title: '车型', dataIndex: 'typeclass_id' },
        { title: '数量', dataIndex: 'quantity' },
      ]} />
    </Card>
  )
}

function InitialStateDetail({ state }: { state: InitialStatePayload | undefined }) {
  if (!state) return <Alert type="warning" showIcon message="该版本没有初始状态明细" />
  const buffer = (bufferId: string) =>
    state.buffer_bod_by_typeclass?.find((item) => item.buffer_id === bufferId)?.wip_bod_by_typeclass || []
  const workshopRows = (state.workshop_wip_by_typeclass || []).flatMap((workshop) =>
    (workshop.wip_bod_by_typeclass || []).map((item) => ({ workshop_id: workshop.workshop_id, ...item })),
  )
  return (
    <div className="setting-readonly-sections">
      <Card size="small" title="状态日期">
        <Descriptions column={1} size="small"><Descriptions.Item label="截至日期">{state.as_of_date || '—'}</Descriptions.Item></Descriptions>
      </Card>
      <QuantityTable title="成品库存（Finished Inventory）" rows={state.finished_inventory_bod_by_typeclass || []} />
      <QuantityTable title="WBS 缓冲在制" rows={buffer('WBS')} />
      <QuantityTable title="PBS 缓冲在制" rows={buffer('PBS')} />
      <Card size="small" title="车间在制（Workshop WIP）">
        <Table {...readonlyTableProps} rowKey={(row) => `${row.workshop_id}-${row.typeclass_id}`} dataSource={workshopRows} columns={[
          { title: '车间', dataIndex: 'workshop_id' },
          { title: '车型', dataIndex: 'typeclass_id' },
          { title: '数量', dataIndex: 'quantity' },
        ]} />
      </Card>
    </div>
  )
}
