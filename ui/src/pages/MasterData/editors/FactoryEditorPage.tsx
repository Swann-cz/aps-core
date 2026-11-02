import { useEffect, useMemo, useState } from 'react'
import { Alert, Card, Input, InputNumber, Space, Table, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/planning'
import { PageHeader } from '../../../components/PageHeader'
import { PageState } from '../../../components/PageState'
import { StatusTag } from '../../../components/StatusTag'
import { VersionEditorFooter } from './VersionEditorFooter'

type ModelDraft = Record<string, any>

export function FactoryEditorPage() {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['factory-model-versions'],
    queryFn: () => api.factoryModelVersions(),
  })
  const active = (listQuery.data || []).find((v: any) => v.status === 'ACTIVE')
  const detailQuery = useQuery({
    queryKey: ['factory-model-version-detail', active?.factory_model_version_id],
    queryFn: () => api.factoryModelVersionDetail(active!.factory_model_version_id),
    enabled: Boolean(active),
  })
  const [draft, setDraft] = useState<ModelDraft | null>(null)
  const [displayName, setDisplayName] = useState('')

  useEffect(() => {
    const versionId = active?.factory_model_version_id ?? null
    if (detailQuery.data && versionId && detailQuery.data.factory_model_version_id === versionId) {
      setDraft(detailQuery.data.factory_model)
      setDisplayName(active?.display_name ?? '')
    }
  }, [active?.display_name, active?.factory_model_version_id, detailQuery.data])

  const dirty = useMemo(
    () => draft !== null && (
      JSON.stringify(draft) !== JSON.stringify(detailQuery.data?.factory_model)
      || displayName.trim() !== active?.display_name
    ),
    [active?.display_name, displayName, draft, detailQuery.data],
  )

  const saveMutation = useMutation({
    mutationFn: () =>
      api.createFactoryModelVersion({
        display_name: displayName.trim(),
        factory_model: draft,
        supersedes_factory_model_version_id: active?.factory_model_version_id ?? undefined,
      }),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        message.success('已创建新的 Factory 版本')
        queryClient.invalidateQueries({ queryKey: ['factory-model-versions'] })
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  if (listQuery.isLoading || detailQuery.isLoading) return <PageState kind="loading" rows={8} />
  if (listQuery.error || detailQuery.error)
    return <PageState kind="system-error" error={listQuery.error || detailQuery.error} onRetry={() => window.location.reload()} />
  if (!active || !draft) return <PageState kind="empty" title="尚未配置工厂与产能模型" />

  const patch = (section: string, index: number, field: string, value: any) => {
    setDraft((prev) => {
      if (!prev) return prev
      const next = { ...prev }
      next[section] = (prev[section] || []).map((item: any, i: number) =>
        i === index ? { ...item, [field]: value } : item,
      )
      return next
    })
  }

  return (
    <div>
      <PageHeader
        title="工厂与产能模型"
        subtitle={draft.version_label || ''}
        actions={<Space><Input aria-label="Factory 短名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="输入短名称" style={{ width: 220 }} /><StatusTag value={active.status} /></Space>}
      />
      <Card size="small" title="车间（Workshops）">
        <Table
          size="small" rowKey="workshop_id" pagination={false}
          dataSource={draft.workshops || []}
          columns={[
            { title: '车间', dataIndex: 'workshop_id' },
            {
              title: '额定 JPH',
              key: 'nominal_jph',
              render: (_: any, record: any, index: number) => (
                <InputNumber
                  min={0} value={record.nominal_jph}
                  onChange={(v) => patch('workshops', index, 'nominal_jph', v)}
                />
              ),
            },
          ]}
        />
      </Card>
      <Card size="small" title="工作模式（Working Modes）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="working_mode_id" pagination={false}
          dataSource={draft.working_modes || []}
          columns={[
            { title: '模式', dataIndex: 'working_mode_id' },
            {
              title: '计划工时',
              key: 'planned_hours',
              render: (_: any, record: any, index: number) => (
                <InputNumber
                  min={0} value={record.planned_hours}
                  onChange={(v) => patch('working_modes', index, 'planned_hours', v)}
                />
              ),
            },
            {
              title: '班次数',
              key: 'shift_count',
              render: (_: any, record: any, index: number) => (
                <InputNumber
                  min={0} value={record.shift_count ?? 1}
                  onChange={(v) => patch('working_modes', index, 'shift_count', v)}
                />
              ),
            },
          ]}
        />
      </Card>
      <Card size="small" title="缓冲（Buffers）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="buffer_id" pagination={false}
          dataSource={draft.buffers || []}
          columns={[
            { title: '缓冲', dataIndex: 'buffer_id' },
            {
              title: '物理最大 WIP',
              key: 'physical_max_wip',
              render: (_: any, record: any, index: number) => (
                <InputNumber
                  min={0} value={record.physical_max_wip}
                  onChange={(v) => patch('buffers', index, 'physical_max_wip', v)}
                />
              ),
            },
          ]}
        />
      </Card>
      <Card size="small" title="车型绑定（Typeclasses）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="typeclass_id" pagination={false}
          dataSource={draft.typeclasses || []}
          columns={[
            { title: '车型', dataIndex: 'typeclass_id' },
            { title: '车间', dataIndex: 'workshop_id' },
            {
              title: '胶龄上限（天）',
              key: 'glue_limit_calendar_days',
              render: (_: any, record: any, index: number) => (
                <InputNumber min={0} precision={0} value={record.glue_limit_calendar_days} placeholder="沿用缺省值" onChange={(v) => patch('typeclasses', index, 'glue_limit_calendar_days', v)} />
              ),
            },
          ]}
        />
      </Card>
      <Alert
        type="info"
        showIcon
        message="胶龄上限使用规则"
        description="清线判断优先使用车型级胶龄上限；车型没有单独设置时，才使用缺省胶龄上限。停线自然日数 D ≥ 胶龄上限 L 时，系统进入清线判断。"
        style={{ marginTop: 12 }}
      />
      <Card size="small" title="流边（Flow Edges）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="from_node" pagination={false}
          dataSource={draft.flow_edges || []}
          columns={[
            { title: 'From', dataIndex: 'from_node' },
            { title: 'To', dataIndex: 'to_node' },
            { title: '当日流转', dataIndex: 'same_day_transfer', render: (v: boolean) => (v ? '是' : '否') },
          ]}
        />
      </Card>
      <Card size="small" title="共享限制（Shared Limits）" style={{ marginTop: 12 }}>
        <Table
          size="small" rowKey="limit" pagination={false}
          dataSource={[
            { limit: 'BS1+BS2 共享焊接 JPH 上限', value: draft.shared_welding_ceiling_jph, field: 'shared_welding_ceiling_jph' },
            { limit: '缺省胶龄上限（天）', value: draft.glue_limit_calendar_days, field: 'glue_limit_calendar_days' },
          ]}
          columns={[
            { title: '限制', dataIndex: 'limit' },
            {
              title: '值',
              key: 'value',
              render: (_: any, record: any) => (
                <InputNumber
                  min={0} value={record.value}
                  onChange={(v) => setDraft((prev) => (prev ? { ...prev, [record.field]: v } : prev))}
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
        onSave={() => displayName.trim() ? saveMutation.mutate() : message.error('请输入非空 Factory 短名称')}
      />
    </div>
  )
}
