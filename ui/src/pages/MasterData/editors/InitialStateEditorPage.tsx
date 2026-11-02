import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Input, InputNumber, Space, Table, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/planning'
import { PageHeader } from '../../../components/PageHeader'
import { PageState } from '../../../components/PageState'
import { StatusTag } from '../../../components/StatusTag'
import { VersionEditorFooter } from './VersionEditorFooter'
import type { InitialStatePayload } from '../../../types/api'

type Qty = { typeclass_id: string; quantity: number }
type WorkshopWip = { workshop_id: string; wip_bod_by_typeclass: Qty[] }
type BufferWip = { buffer_id: string; wip_bod_by_typeclass: Qty[] }
type WorkshopWipRow = Qty & { key: string; workshop_id: string }

function factoryTypeclassIds(factoryModel: Record<string, any> | null | undefined): string[] {
  if (!factoryModel) return []
  return Array.from(new Set(
    (factoryModel.typeclasses || []).map((item: any) => String(item.typeclass_id)),
  )) as string[]
}

function normalizeTypeclassQuantities(
  current: Qty[],
  factoryModel: Record<string, any> | null | undefined,
): Qty[] {
  const expected = factoryTypeclassIds(factoryModel)
  const orderedTypeclasses = Array.from(new Set([
    ...expected,
    ...current.map((item) => String(item.typeclass_id)),
  ]))
  const quantities = new Map(
    current.map((item) => [String(item.typeclass_id), Number(item.quantity)]),
  )
  return orderedTypeclasses.map((typeclassId) => ({
    typeclass_id: typeclassId,
    quantity: quantities.get(typeclassId) ?? 0,
  }))
}

function normalizeBufferWip(
  current: BufferWip[],
  factoryModel: Record<string, any> | null | undefined,
): BufferWip[] {
  if (!factoryModel) return current
  const buffers = (factoryModel.buffers || []).map((item: any) => String(item.buffer_id))
  const currentByBuffer = new Map(current.map((item) => [String(item.buffer_id), item]))
  const normalized = buffers.map((bufferId: string) => ({
    buffer_id: bufferId,
    wip_bod_by_typeclass: normalizeTypeclassQuantities(
      currentByBuffer.get(bufferId)?.wip_bod_by_typeclass || [],
      factoryModel,
    ),
  }))
  const historicalExtras = current.filter((item) => !buffers.includes(String(item.buffer_id)))
  return [...normalized, ...historicalExtras]
}

function normalizeWorkshopWip(
  current: WorkshopWip[],
  factoryModel: Record<string, any> | null | undefined,
): WorkshopWip[] {
  if (!factoryModel) return current
  const workshops = (factoryModel.workshops || []).map((item: any) => String(item.workshop_id))
  const mappings = (factoryModel.typeclasses || []).map((item: any) => ({
    typeclass_id: String(item.typeclass_id),
    workshop_id: String(item.workshop_id),
  }))
  const allTypeclasses = Array.from(new Set(mappings.map((item: any) => item.typeclass_id))) as string[]
  const currentByWorkshop = new Map(current.map((item) => [String(item.workshop_id), item]))
  const normalized = workshops.map((workshopId: string) => {
    const existing = currentByWorkshop.get(workshopId)?.wip_bod_by_typeclass || []
    const mapped = mappings.filter((item: any) => item.workshop_id === workshopId).map((item: any) => item.typeclass_id)
    const expected = mapped.length > 0 ? mapped : allTypeclasses
    const orderedTypeclasses = Array.from(new Set([
      ...expected,
      ...existing.map((item) => String(item.typeclass_id)),
    ]))
    const quantities = new Map(existing.map((item) => [String(item.typeclass_id), Number(item.quantity)]))
    return {
      workshop_id: workshopId,
      wip_bod_by_typeclass: orderedTypeclasses.map((typeclassId) => ({
        typeclass_id: typeclassId,
        quantity: quantities.get(typeclassId) ?? 0,
      })),
    }
  })
  const historicalExtras = current.filter((item) => !workshops.includes(String(item.workshop_id)))
  return [...normalized, ...historicalExtras]
}

export function InitialStateEditorPage() {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['initial-state-snapshots'],
    queryFn: () => api.initialStateSnapshots(),
  })
  const active = (listQuery.data || []).find((v: any) => v.status === 'ACTIVE')
  const factoryListQuery = useQuery({
    queryKey: ['factory-model-versions'],
    queryFn: () => api.factoryModelVersions(),
  })
  const activeFactory = (factoryListQuery.data || []).find((v: any) => v.status === 'ACTIVE')
  const factoryDetailQuery = useQuery({
    queryKey: ['factory-model-version-detail', activeFactory?.factory_model_version_id],
    queryFn: () => api.factoryModelVersionDetail(activeFactory!.factory_model_version_id),
    enabled: Boolean(activeFactory),
  })
  const detailQuery = useQuery({
    queryKey: ['initial-state-snapshot-detail', active?.initial_state_snapshot_id],
    queryFn: () => api.initialStateSnapshotDetail(active!.initial_state_snapshot_id),
    enabled: Boolean(active),
  })
  const [draft, setDraft] = useState<InitialStatePayload | null>(null)
  const [displayName, setDisplayName] = useState('')

  useEffect(() => {
    const snapshotId = active?.initial_state_snapshot_id ?? null
    if (detailQuery.data && factoryDetailQuery.data && snapshotId && detailQuery.data.initial_state_snapshot_id === snapshotId) {
      const factoryModel = (factoryDetailQuery.data as any)?.factory_model
      setDraft({
        ...detailQuery.data.initial_state,
        finished_inventory_bod_by_typeclass: normalizeTypeclassQuantities(
          detailQuery.data.initial_state.finished_inventory_bod_by_typeclass || [],
          factoryModel,
        ),
        buffer_bod_by_typeclass: normalizeBufferWip(
          detailQuery.data.initial_state.buffer_bod_by_typeclass || [],
          factoryModel,
        ),
        workshop_wip_by_typeclass: normalizeWorkshopWip(
          detailQuery.data.initial_state.workshop_wip_by_typeclass || [],
          factoryModel,
        ),
      })
      setDisplayName(active?.display_name ?? '')
    }
  }, [active?.display_name, active?.initial_state_snapshot_id, detailQuery.data, factoryDetailQuery.data])

  const dirty = useMemo(
    () =>
      draft !== null &&
      (JSON.stringify(draft) !== JSON.stringify(detailQuery.data?.initial_state)
        || displayName.trim() !== active?.display_name),
    [active?.display_name, displayName, draft, detailQuery.data],
  )

  const saveMutation = useMutation({
    mutationFn: () =>
      api.createInitialStateSnapshot({
        display_name: displayName.trim(),
        initial_state: draft || detailQuery.data?.initial_state,
        supersedes_initial_state_snapshot_id: active?.initial_state_snapshot_id ?? undefined,
      }),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        message.success('已创建新的 Initial State 版本')
        queryClient.invalidateQueries({ queryKey: ['initial-state-snapshots'] })
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  if (listQuery.isLoading || detailQuery.isLoading || factoryListQuery.isLoading || factoryDetailQuery.isLoading)
    return <PageState kind="loading" rows={6} />
  if (listQuery.error || detailQuery.error || factoryListQuery.error || factoryDetailQuery.error)
    return <PageState kind="system-error" error={listQuery.error || detailQuery.error || factoryListQuery.error || factoryDetailQuery.error} onRetry={() => window.location.reload()} />
  if (!active || !draft) return <PageState kind="empty" title="尚未配置初始库存与在制" />

  const patchSection = (section: keyof InitialStatePayload, values: Qty[]) => {
    setDraft((prev) => (prev ? { ...prev, [section]: values } : prev))
  }

  const qtyTable = (
    label: string,
    rows: Qty[],
    onChangeRows: (values: Qty[]) => void,
  ) => (
    <Card
      size="small"
      title={label}
      style={{ marginTop: 12 }}
    >
      <Table
        size="small" rowKey="typeclass_id" pagination={false}
        dataSource={rows}
        locale={{ emptyText: '当前 Factory 没有可配置的车型' }}
        columns={[
          { title: '车型', dataIndex: 'typeclass_id' },
          {
            title: '数量',
            key: 'quantity',
            render: (_: any, record: Qty, index: number) => (
              <InputNumber
                aria-label={`${label} ${record.typeclass_id} 数量`}
                min={0}
                value={record.quantity}
                onChange={(v) => {
                  const next = rows.map((r, i) =>
                    i === index ? { ...r, quantity: v ?? 0 } : r,
                  )
                  onChangeRows(next)
                }}
              />
            ),
          },
        ]}
      />
    </Card>
  )

  const finished = draft.finished_inventory_bod_by_typeclass || []
  const buffers = draft.buffer_bod_by_typeclass || []
  const wbs = buffers.find((b: any) => b.buffer_id === 'WBS')
  const pbs = buffers.find((b: any) => b.buffer_id === 'PBS')
  const patchBuffer = (bufferId: string, values: Qty[]) => {
    setDraft((prev) => {
      if (!prev) return prev
      const current = prev.buffer_bod_by_typeclass || []
      const found = current.some((buffer) => buffer.buffer_id === bufferId)
      const next = found
        ? current.map((buffer) => buffer.buffer_id === bufferId ? { ...buffer, wip_bod_by_typeclass: values } : buffer)
        : [...current, { buffer_id: bufferId, wip_bod_by_typeclass: values }]
      return { ...prev, buffer_bod_by_typeclass: next }
    })
  }
  const workshopWip = (draft.workshop_wip_by_typeclass || []) as WorkshopWip[]
  const workshopRows: WorkshopWipRow[] = workshopWip.flatMap((workshop) =>
    workshop.wip_bod_by_typeclass.map((item) => ({
      key: `${workshop.workshop_id}-${item.typeclass_id}`,
      workshop_id: workshop.workshop_id,
      typeclass_id: item.typeclass_id,
      quantity: item.quantity,
    })),
  )
  const patchWorkshopWip = (workshopId: string, typeclassId: string, quantity: number) => {
    setDraft((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        workshop_wip_by_typeclass: (prev.workshop_wip_by_typeclass || []).map((workshop) => (
          workshop.workshop_id === workshopId
            ? {
                ...workshop,
                wip_bod_by_typeclass: workshop.wip_bod_by_typeclass.map((item) => (
                  item.typeclass_id === typeclassId ? { ...item, quantity } : item
                )),
              }
            : workshop
        )),
      }
    })
  }

  return (
    <div>
      <PageHeader
        title="初始库存与在制"
        subtitle="成品库存 / 车间在制 / WBS / PBS 期初状态"
        actions={<Space><Input aria-label="Initial 短名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="输入短名称" style={{ width: 220 }} /><StatusTag value={active.status} /></Space>}
      />
      <Alert
        type="info"
        showIcon
        message="已按当前 Factory 补齐必需车型"
        description="缺失数量按 0 初始化；保存新版本后才会生效。"
      />
      {qtyTable(
        '成品库存（Finished Inventory）',
        finished,
        (values) => patchSection('finished_inventory_bod_by_typeclass', values),
      )}
      {qtyTable('WBS 缓冲在制', wbs?.wip_bod_by_typeclass || [], (values) => patchBuffer('WBS', values))}
      {qtyTable('PBS 缓冲在制', pbs?.wip_bod_by_typeclass || [], (values) => patchBuffer('PBS', values))}
      <Card size="small" title="车间在制（Workshop WIP）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="key" pagination={false}
          dataSource={workshopRows}
          locale={{ emptyText: '当前 Factory 没有可配置的车间 / 车型组合' }}
          columns={[
            {
              title: '车间',
              dataIndex: 'workshop_id',
              width: 150,
              render: (value: string) => <strong>{value}</strong>,
              onCell: (record: WorkshopWipRow) => {
                const first = workshopRows.findIndex((item) => item.workshop_id === record.workshop_id)
                const count = workshopRows.filter((item) => item.workshop_id === record.workshop_id).length
                return { rowSpan: workshopRows[first]?.key === record.key ? count : 0 }
              },
            },
            { title: '车型', dataIndex: 'typeclass_id', width: 180 },
            {
              title: '初始数量',
              key: 'quantity',
              render: (_: unknown, record: WorkshopWipRow) => (
                <InputNumber
                  aria-label={`${record.workshop_id} ${record.typeclass_id} 初始 WIP`}
                  min={0}
                  precision={0}
                  value={record.quantity}
                  onChange={(value) => patchWorkshopWip(
                    record.workshop_id,
                    record.typeclass_id,
                    value ?? 0,
                  )}
                  style={{ width: 180 }}
                />
              ),
            },
          ]}
        />
      </Card>
      <VersionEditorFooter
        dirty={dirty}
        saving={saveMutation.isPending}
        onCancel={() => window.history.back()}
        onSave={() => displayName.trim() ? saveMutation.mutate() : message.error('请输入非空 Initial 短名称')}
      />
    </div>
  )
}
