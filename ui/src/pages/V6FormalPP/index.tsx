import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Descriptions, Drawer, Input, Select, Space, Table, Tag, Typography } from 'antd'
import { AuditOutlined, CalendarOutlined, EyeOutlined, NodeIndexOutlined, TableOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import type { V6FormalPPVersion } from '../../types/v6'
import { rememberFormalId } from '../../utils/v6FormalViewAuthority'

function formalModeLabel(item: V6FormalPPVersion): string {
  return item.input_bundle.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产' : 'Rolling'
}

function formalOptionLabel(item: V6FormalPPVersion): string {
  return `${item.display_name} · ${formalModeLabel(item)} · ${item.saved_at}`
}

export function V6FormalPPLibrary() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [search, setSearch] = useState('')
  const [oldId, setOldId] = useState('')
  const [newId, setNewId] = useState('')
  const [detailId, setDetailId] = useState<string | null>(null)
  const query = useQuery({ queryKey: ['v6', 'formal'], queryFn: v6Api.formalVersions, retry: false })
  const detailQuery = useQuery({ queryKey: ['v6', 'formal', detailId], queryFn: () => v6Api.formalVersion(detailId!), enabled: Boolean(detailId), retry: false })
  const openFormal = (formalPpId: string, view: 'annual' | 'filling') => {
    rememberFormalId(formalPpId)
    navigate(`/v6/formal-pp/${encodeURIComponent(formalPpId)}/${view}`)
  }
  const versions = useMemo(() => (query.data || []).filter((item) => {
    const needle = search.trim().toLowerCase()
    if (!needle) return true
    return [item.display_name, item.formal_pp_id, item.parent_formal_pp_id, ...item.input_bundle.business_id_snapshots.map((value) => value.business_id)].some((value) => String(value || '').toLowerCase().includes(needle))
  }), [query.data, search])

  useEffect(() => {
    const focus = searchParams.get('focus')
    if (!focus || !(query.data || []).some((item) => item.formal_pp_id === focus)) return
    setNewId(focus)
    const target = query.data!.find((item) => item.formal_pp_id === focus)
    if (target?.parent_formal_pp_id) setOldId(target.parent_formal_pp_id)
  }, [query.data, searchParams])

  if (query.isLoading) return <PageState kind="loading" rows={7} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  const selectedOld = (query.data || []).find((item) => item.formal_pp_id === oldId)
  const selectedNew = (query.data || []).find((item) => item.formal_pp_id === newId)
  const orderValid = Boolean(selectedOld && selectedNew && new Date(selectedNew.saved_at).getTime() > new Date(selectedOld.saved_at).getTime())
  const formalName = (formalId: string | null | undefined) => (
    (query.data || []).find((item) => item.formal_pp_id === formalId)?.display_name
    || '父版本详情中查看'
  )
  const options = (query.data || []).map((item) => ({ value: item.formal_pp_id, label: formalOptionLabel(item) }))

  return <div className="page-container v6-formal-page">
    <PageHeader title="正式 PP 库 / 比较" subtitle="FormalPPVersion 不可变；只支持固定两个正式版本，上旧下新比较" />
    <Alert
      type={(query.data || []).length < 2 ? 'warning' : 'info'}
      showIcon
      message={(query.data || []).length < 2 ? '当前正式 PP 数量不足，暂不能比较' : '正式 PP 比较规则'}
      description="比较至少需要两个正式 PP。上方选择较早的旧版本，下方选择较晚的新版本；Dev. 固定表示“新版本 − 旧版本”。"
      style={{ marginBottom: 12 }}
    />
    <Card className="v6-compare-picker" title={<Space><AuditOutlined />选择比较版本</Space>}>
      <div className="v6-compare-stack">
        <div className="old"><span>上方 · 旧版本</span><Select showSearch optionFilterProp="label" value={oldId || undefined} options={options} onChange={setOldId} placeholder="选择旧版本" /></div>
        <div className="v6-compare-arrow">↓</div>
        <div className="new"><span>下方 · 新版本</span><Select showSearch optionFilterProp="label" value={newId || undefined} options={options} onChange={setNewId} placeholder="选择新版本" /></div>
      </div>
      {!orderValid && oldId && newId && <Alert type="warning" showIcon message="新版本保存时间必须晚于旧版本" style={{ marginTop: 12 }} />}
      <Button type="primary" icon={<AuditOutlined />} disabled={!orderValid} style={{ marginTop: 14 }} onClick={() => navigate(`/v6/formal-compare?old=${encodeURIComponent(oldId)}&new=${encodeURIComponent(newId)}`)}>开始比较 · Dev. = 新 − 旧</Button>
    </Card>
    <Card title="正式 PP 版本" extra={<Input.Search allowClear value={search} onChange={(event) => setSearch(event.target.value)} placeholder="搜索名称或详情 ID" style={{ width: 320 }} />} style={{ marginTop: 16 }}>
      <Table rowKey="formal_pp_id" dataSource={versions} pagination={{ pageSize: 12 }} columns={[
        { title: '正式 PP', dataIndex: 'display_name', render: (value) => <strong>{value}</strong> },
        { title: '模式', render: (_, row) => <Tag color={row.input_bundle.generation_mode === 'INITIAL_FROM_ZERO' ? 'blue' : 'orange'}>{row.input_bundle.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产' : 'Rolling'}</Tag> },
        { title: '父 PP', dataIndex: 'parent_formal_pp_id', render: (value) => value ? formalName(String(value)) : '—' },
        { title: '输入摘要', render: (_, row) => row.input_bundle.business_id_snapshots.slice(0, 4).map((item) => <Tag key={`${row.formal_pp_id}-${item.kind}`}>{item.kind}: {item.business_id}</Tag>) },
        { title: '保存人', dataIndex: 'saved_by' },
        { title: '保存时间', dataIndex: 'saved_at' },
        { title: '操作', render: (_, row) => <Space wrap><Button size="small" icon={<CalendarOutlined />} onClick={() => openFormal(row.formal_pp_id, 'annual')}>年度总览</Button><Button size="small" icon={<TableOutlined />} onClick={() => openFormal(row.formal_pp_id, 'filling')}>月度 Filling</Button><Button size="small" icon={<EyeOutlined />} onClick={() => setDetailId(row.formal_pp_id)}>预览</Button>{row.parent_formal_pp_id && <Button size="small" icon={<NodeIndexOutlined />} onClick={() => { setOldId(row.parent_formal_pp_id!); setNewId(row.formal_pp_id); window.scrollTo({ top: 0, behavior: 'smooth' }) }}>父子比较</Button>}</Space> },
      ]} />
    </Card>
    <Drawer title="不可变 FormalPPVersion 详情" open={Boolean(detailId)} onClose={() => setDetailId(null)} width={760}>
      {detailQuery.isLoading ? <PageState kind="loading" rows={8} /> : detailQuery.isError ? <PageState kind="system-error" error={detailQuery.error} /> : detailQuery.data ? <><Descriptions bordered size="small" column={1}><Descriptions.Item label="正式 PP">{detailQuery.data.display_name}</Descriptions.Item><Descriptions.Item label="ID">{detailQuery.data.formal_pp_id}</Descriptions.Item><Descriptions.Item label="父 PP">{detailQuery.data.parent_formal_pp_id || '—'}</Descriptions.Item><Descriptions.Item label="保存审计">{detailQuery.data.saved_by} · {detailQuery.data.saved_at}</Descriptions.Item><Descriptions.Item label="备注">{detailQuery.data.work_note}</Descriptions.Item></Descriptions><Typography.Title level={5} style={{ marginTop: 16 }}>完整冻结快照</Typography.Title><pre className="v6-json-preview">{JSON.stringify(detailQuery.data, null, 2)}</pre></> : null}
    </Drawer>
  </div>
}
