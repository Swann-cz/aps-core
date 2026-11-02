import { useEffect, useMemo, useState } from 'react'
import { Button, Card, Input, InputNumber, Space, Table, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/planning'
import { PageHeader } from '../../../components/PageHeader'
import { PageState } from '../../../components/PageState'
import { StatusTag } from '../../../components/StatusTag'
import type { WipTargetItem, WipTargetVersionDetail } from '../../../types/api'

const NODE_ROWS: { node_type: 'WORKSHOP' | 'BUFFER'; node_id: string; label: string }[] = [
  { node_type: 'WORKSHOP', node_id: 'BS1', label: 'BS1 目标 WIP' },
  { node_type: 'WORKSHOP', node_id: 'BS2', label: 'BS2 目标 WIP' },
  { node_type: 'WORKSHOP', node_id: 'PS', label: 'PS 目标 WIP' },
  { node_type: 'WORKSHOP', node_id: 'AS_MAINLINE', label: 'AS 主线目标 WIP' },
  { node_type: 'WORKSHOP', node_id: 'AS_FINISH_LINE', label: 'AS 终线目标 WIP' },
  { node_type: 'BUFFER', node_id: 'WBS', label: 'WBS 目标 WIP' },
  { node_type: 'BUFFER', node_id: 'PBS', label: 'PBS 目标 WIP' },
]

export function WipTargetEditorPage() {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['wip-target-versions'],
    queryFn: () => api.wipTargetVersions(),
  })
  const active = (listQuery.data || []).find((v) => v.status === 'ACTIVE')
  const detailQuery = useQuery({
    queryKey: ['wip-target-version-detail', active?.wip_target_version_id],
    queryFn: () => api.wipTargetVersionDetail(active!.wip_target_version_id),
    enabled: Boolean(active),
  })

  const [targets, setTargets] = useState<Record<string, number>>({})
  const [displayName, setDisplayName] = useState('')
  useEffect(() => {
    if (detailQuery.data) {
      const next: Record<string, number> = {}
      for (const item of detailQuery.data.targets) {
        next[item.node_id] = item.target_quantity
      }
      setTargets(next)
      setDisplayName(active?.display_name ?? '')
    }
  }, [active?.display_name, detailQuery.data])

  const dirty = useMemo(() => {
    const current = new Map((detailQuery.data?.targets || []).map((t: WipTargetItem) => [t.node_id, t.target_quantity]))
    return NODE_ROWS.some((row) => (targets[row.node_id] ?? -1) !== (current.get(row.node_id) ?? -1))
      || displayName.trim() !== active?.display_name
  }, [active?.display_name, detailQuery.data, displayName, targets])

  const saveMutation = useMutation({
    mutationFn: () =>
      api.createWipTargetVersion({
        display_name: displayName.trim(),
        targets: NODE_ROWS.map((row) => ({
          node_type: row.node_type,
          node_id: row.node_id,
          target_quantity: targets[row.node_id] ?? 0,
        })),
        supersedes_wip_target_version_id: active?.wip_target_version_id ?? null,
      }),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        message.success('已创建新的 WIP Target 版本')
        queryClient.invalidateQueries({ queryKey: ['wip-target-versions'] })
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => api.activateWipTargetVersion(versionId),
    onSuccess: (result) => {
      if (result.outcome === 'ACTIVATED') {
        message.success('已激活为当前版本')
        queryClient.invalidateQueries({ queryKey: ['wip-target-versions'] })
      }
    },
  })

  if (listQuery.isLoading || detailQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (listQuery.error || detailQuery.error)
    return <PageState kind="system-error" error={listQuery.error || detailQuery.error} onRetry={() => window.location.reload()} />
  if (!active) return <PageState kind="empty" title="尚未配置 WIP 目标水位版本" />

  const newest = (listQuery.data || [])[0]
  return (
    <div>
      <PageHeader
        title="WIP 目标水位"
        subtitle="Soft target：进入候选选择与解释，不构成硬约束"
        actions={
          <Space>
            <Input aria-label="WIP 短名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="输入短名称" style={{ width: 220 }} />
            {detailQuery.data && (
              <StatusTag value={detailQuery.data.status} />
            )}
            {newest && newest.status !== 'ACTIVE' && (
              <Button onClick={() => activateMutation.mutate(newest.wip_target_version_id)}>
                激活为当前版本
              </Button>
            )}
          </Space>
        }
      />
      <Card size="small">
        <Table
          size="small"
          rowKey="node_id"
          pagination={false}
          dataSource={NODE_ROWS}
          columns={[
            { title: '节点', dataIndex: 'node_id', width: 120 },
            { title: '类型', dataIndex: 'node_type', width: 120 },
            {
              title: '目标 WIP',
              key: 'target',
              render: (_, row) => (
                <InputNumber
                  aria-label={row.label}
                  min={0}
                  value={targets[row.node_id] ?? 0}
                  onChange={(value) => setTargets((prev) => ({ ...prev, [row.node_id]: value ?? 0 }))}
                />
              ),
            },
          ]}
        />
        <div className="version-editor-footer">
          <span>{dirty ? '有未保存修改' : '没有修改'}</span>
          <Space>
            <Button onClick={() => window.history.back()}>取消</Button>
            <Button
              type="primary"
              disabled={!dirty}
              loading={saveMutation.isPending}
              onClick={() => displayName.trim() ? saveMutation.mutate() : message.error('请输入非空 WIP 短名称')}
            >
              保存新版本
            </Button>
          </Space>
        </div>
      </Card>
    </div>
  )
}
