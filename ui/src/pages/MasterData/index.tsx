import { useState } from 'react'
import { Alert, Button, Modal, Popconfirm, Space, Table, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { StatusTag } from '../../components/StatusTag'
import { BaseSettingRow } from './BaseSettingRow'
import { SETTING_META, SettingReadOnlyDrawer, type SettingKind } from './SettingReadOnlyDrawer'

export function MasterData() {
  const navigate = useNavigate()
  const [historyKind, setHistoryKind] = useState<SettingKind | null>(null)
  const [viewKind, setViewKind] = useState<SettingKind | null>(null)

  const factoryQuery = useQuery({
    queryKey: ['factory-model-versions'],
    queryFn: () => api.factoryModelVersions(),
  })
  const calendarQuery = useQuery({
    queryKey: ['calendar-versions'],
    queryFn: () => api.calendarVersions(),
  })
  const wipQuery = useQuery({
    queryKey: ['wip-target-versions'],
    queryFn: () => api.wipTargetVersions(),
  })
  const initialQuery = useQuery({
    queryKey: ['initial-state-snapshots'],
    queryFn: () => api.initialStateSnapshots(),
  })

  const activeFactory = (factoryQuery.data || []).find((v) => v.status === 'ACTIVE')
  const activeCalendar = (calendarQuery.data || []).find((v) => v.status === 'ACTIVE')
  const activeWip = (wipQuery.data || []).find((v) => v.status === 'ACTIVE')
  const activeInitial = (initialQuery.data || []).find((v) => v.status === 'ACTIVE')

  const rows: { kind: SettingKind; ready: boolean; versionName: string | null; updatedAt: string | null }[] = [
    {
      kind: 'factory',
      ready: Boolean(activeFactory),
      versionName: activeFactory?.display_name ?? null,
      updatedAt: (activeFactory as any)?.created_at ?? null,
    },
    {
      kind: 'calendar',
      ready: Boolean(activeCalendar),
      versionName: activeCalendar?.display_name ?? null,
      updatedAt: (activeCalendar as any)?.created_at ?? null,
    },
    {
      kind: 'wip',
      ready: Boolean(activeWip),
      versionName: activeWip?.display_name ?? null,
      updatedAt: activeWip?.created_at ?? null,
    },
    {
      kind: 'initial',
      ready: Boolean(activeInitial),
      versionName: activeInitial?.display_name ?? null,
      updatedAt: activeInitial?.created_at ?? null,
    },
  ]

  const loading =
    factoryQuery.isLoading || calendarQuery.isLoading || wipQuery.isLoading || initialQuery.isLoading
  const error =
    factoryQuery.error || calendarQuery.error || wipQuery.error || initialQuery.error

  if (loading) return <PageState kind="loading" rows={4} />
  if (error) return <PageState kind="system-error" error={error} onRetry={() => window.location.reload()} />

  const readyCount = rows.filter((row) => row.ready).length
  const latestChanged = rows
    .filter((row) => row.updatedAt)
    .sort((left, right) => String(right.updatedAt).localeCompare(String(left.updatedAt)))[0]

  return (
    <div>
      <PageHeader title="基础设置" subtitle="先准备好这四项，才能发起年度排产" />
      <Alert
        type={readyCount === rows.length ? 'success' : 'warning'}
        showIcon
        style={{ marginBottom: 14 }}
        message={`基础设置完整度：${readyCount} / ${rows.length}`}
        description={
          <Space direction="vertical" size={2}>
            <span>当前生效概况：{readyCount === rows.length ? '四项均已就绪' : '仍有未就绪项目'}</span>
            <span>最近变更：{latestChanged ? SETTING_META[latestChanged.kind].title : '当前接口未提供'}</span>
            <span>激活新基础版本只影响未来 Session，不会改写已有 PlanVersion。</span>
          </Space>
        }
      />
      <div className="base-setting-list">
        {rows.map((row) => (
          <BaseSettingRow
            key={row.kind}
            title={SETTING_META[row.kind].title}
            ready={row.ready}
            versionName={row.versionName}
            updatedAt={row.updatedAt}
            summary={
              row.ready ? (
                <span>当前生效版本已就绪，可进入排产</span>
              ) : (
                <span className="muted">尚未配置生效版本，需先建立</span>
              )
            }
            onView={() => setViewKind(row.kind)}
            onEdit={() => navigate(SETTING_META[row.kind].editRoute)}
            onHistory={() => setHistoryKind(row.kind)}
          />
        ))}
      </div>

      {viewKind ? <SettingReadOnlyDrawer
        key={viewKind}
        kind={viewKind}
        record={{
          factory: activeFactory,
          calendar: activeCalendar,
          wip: activeWip,
          initial: activeInitial,
        }[viewKind]}
        onClose={() => setViewKind(null)}
      /> : null}
      <HistoryModal
        kind={historyKind}
        lists={{
          factory: factoryQuery.data || [],
          calendar: calendarQuery.data || [],
          wip: wipQuery.data || [],
          initial: initialQuery.data || [],
        }}
        onClose={() => setHistoryKind(null)}
      />
    </div>
  )
}

function HistoryModal({
  kind,
  lists,
  onClose,
}: {
  kind: SettingKind | null
  lists: Record<SettingKind, any[]>
  onClose: () => void
}) {
  const queryClient = useQueryClient()
  const mutation = useMutation({
    mutationFn: ({ action, targetKind, id }: { action: 'activate' | 'archive'; targetKind: SettingKind; id: string }) => {
      if (action === 'activate') {
        if (targetKind === 'factory') return api.activateFactoryModelVersion(id)
        if (targetKind === 'calendar') return api.activateCalendarVersion(id)
        if (targetKind === 'wip') return api.activateWipTargetVersion(id)
        return api.activateInitialStateSnapshot(id)
      }
      if (targetKind === 'factory') return api.archiveFactoryModelVersion(id)
      if (targetKind === 'calendar') return api.archiveCalendarVersion(id)
      if (targetKind === 'wip') return api.archiveWipTargetVersion(id)
      return api.archiveInitialStateSnapshot(id)
    },
    onSuccess: (result, variables) => {
      const expected = variables.action === 'activate' ? 'ACTIVATED' : 'ARCHIVED'
      if (result.outcome !== expected) {
        message.error(result.message || `${variables.action === 'activate' ? '激活' : '删除'}失败：${result.outcome}`)
        return
      }
      message.success(variables.action === 'activate' ? '已激活为当前版本' : '已从日常历史列表删除')
      const queryKey: Record<SettingKind, string[]> = {
        factory: ['factory-model-versions'],
        calendar: ['calendar-versions'],
        wip: ['wip-target-versions'],
        initial: ['initial-state-snapshots'],
      }
      void queryClient.invalidateQueries({ queryKey: queryKey[variables.targetKind] })
    },
    onError: (error: unknown, variables) => {
      message.error(error instanceof Error ? error.message : `${variables.action === 'activate' ? '激活' : '删除'}失败`)
    },
  })
  if (!kind) return null
  const idField: Record<SettingKind, string> = {
    factory: 'factory_model_version_id',
    calendar: 'calendar_version_id',
    wip: 'wip_target_version_id',
    initial: 'initial_state_snapshot_id',
  }
  const data = lists[kind] || []
  const pending = mutation.isPending ? mutation.variables : null
  return (
    <Modal
      title={`${SETTING_META[kind].title} · 版本历史`}
      open={Boolean(kind)}
      onCancel={onClose}
      footer={<Button onClick={onClose}>关闭</Button>}
      width={820}
    >
      <Table
        size="small"
        rowKey={idField[kind]}
        dataSource={data}
        pagination={false}
        columns={[
          { title: '短名称', dataIndex: 'display_name' },
          { title: '年份', render: (_: unknown, record: any) => record.calendar_year ?? record.planning_year ?? '—' },
          { title: '状态', dataIndex: 'status', render: (v: string) => <StatusTag value={v} /> },
          { title: '创建时间', render: (_: unknown, record: any) => record.created_at ?? '—' },
          {
            title: '操作',
            key: 'actions',
            width: 168,
            render: (_: unknown, record: any) => {
              const id = String(record[idField[kind]])
              if (record.status === 'ACTIVE') return <span className="muted">当前激活</span>
              const activateLoading = pending?.action === 'activate' && pending.id === id
              const archiveLoading = pending?.action === 'archive' && pending.id === id
              return (
                <Space size={4}>
                  <Button
                    size="small"
                    type="link"
                    loading={activateLoading}
                    disabled={mutation.isPending}
                    onClick={() => mutation.mutate({ action: 'activate', targetKind: kind, id })}
                  >
                    激活
                  </Button>
                  <Popconfirm
                    title="删除这个未激活版本？"
                    description="仅从日常列表移除；历史计划与审计证据仍会保留。"
                    okText="删除"
                    cancelText="取消"
                    onConfirm={() => mutation.mutate({ action: 'archive', targetKind: kind, id })}
                  >
                    <Button size="small" type="link" danger loading={archiveLoading} disabled={mutation.isPending}>
                      删除
                    </Button>
                  </Popconfirm>
                </Space>
              )
            },
          },
        ]}
      />
    </Modal>
  )
}
