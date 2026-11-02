import { useState } from 'react'
import { Alert, App, Button, Card, Form, Input, Space, Table, Upload } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { Select } from 'antd'
import { core, PlanImportError, type ImportError, type PlanPreview } from '../../api/core'
import { useCore } from '../../app/CoreContext'
import { PageHeader } from '../../components/PageHeader'
import { FullImport } from './FullImport'

const uploads = [
  { kind: 'sales', label: '销售计划', hint: '必填：月份、车型类别、PR、WS。' },
  { kind: 'initial', label: '期初在制', hint: '可选；不上传则复制来源方案的期初数据。' },
  { kind: 'calendar', label: '生产行事历', hint: '可选；不上传则沿用来源方案同月同日的生产标记，未找到的日期按周一至周五可生产。' },
] as const
type Kind = typeof uploads[number]['kind']
export function SplitImport({ onCreated }: { onCreated?: () => void }) {
  const state = useCore()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [name, setName] = useState('')
  const [baseId, setBaseId] = useState(state.scenario?.id)
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [start, setStart] = useState(`${year}-01-01`)
  const [end, setEnd] = useState(`${year}-12-31`)
  const [files, setFiles] = useState<Partial<Record<Kind, File>>>({})
  const [result, setResult] = useState<PlanPreview | null>(null)
  const [errors, setErrors] = useState<ImportError[]>([])
  const [failure, setFailure] = useState('')
  const invalidate = () => { setResult(null); setErrors([]); setFailure('') }
  const payload = (create = false) => {
    const data = new FormData()
    data.append('base_id', baseId!)
    data.append('start', start)
    data.append('end', end)
    uploads.forEach(({ kind }) => { if (files[kind]) data.append(kind, files[kind]!) })
    if (create) data.append('name', name.trim())
    return data
  }
  const onError = (error: Error) => {
    setResult(null)
    setFailure(error.message)
    setErrors(error instanceof PlanImportError ? error.errors : [])
  }
  const preview = useMutation({ mutationFn: () => core.previewPlan(payload()), onSuccess: data => {
    setResult(data); setErrors(data.errors); setFailure(data.ok ? '' : '预检未通过，请修改后重新预检。')
  }, onError })
  const create = useMutation({ mutationFn: () => core.createPlan(payload(true)), onSuccess: summary => {
    state.update(summary); state.select(summary.id)
    void message.success('方案已创建，尚未运行。')
    if (onCreated) onCreated()
    else navigate('/planning-conditions')
  }, onError })
  const download = useMutation({ mutationFn: (kind: Kind) => core.template(kind, baseId!, year), onSuccess: (blob, kind) => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `${uploads.find(item => item.kind === kind)!.label}-${year}.xlsx`
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
  }, onError: (error: Error) => { void message.error(error.message) } })
  const busy = preview.isPending || create.isPending
  const ready = Boolean(name.trim() && baseId && start && end && files.sales)
  return <>
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Card title="分文件导入"><Form layout="vertical" disabled={busy} style={{ maxWidth: 760 }}>
        <Form.Item label="方案名称" required><Input value={name} onChange={event => { setName(event.target.value); invalidate() }} /></Form.Item>
        <Form.Item label="工厂设置来自" required><Select value={baseId} loading={state.list.isLoading} placeholder="请选择已有方案" options={state.scenarios.map(s => ({ value: s.id, label: s.name }))} onChange={value => { setBaseId(value); invalidate() }} /></Form.Item>
        <Form.Item label="计划期" required><Space wrap>
          <Input aria-label="计划年份" type="number" value={year} style={{ width: 110 }} onChange={event => {
            const value = event.target.value
            setYear(value); setStart(`${value}-01-01`); setEnd(`${value}-12-31`); invalidate()
          }} />
          <Input aria-label="计划开始日期" type="date" value={start} onChange={event => { setStart(event.target.value); invalidate() }} />
          <span>至</span><Input aria-label="计划结束日期" type="date" value={end} min={start} onChange={event => { setEnd(event.target.value); invalidate() }} />
        </Space></Form.Item>
        {uploads.map(({ kind, label, hint }) => <Form.Item key={kind} label={label} required={kind === 'sales'} extra={hint}>
          <Space align="start" wrap>
            <Upload accept=".xlsx" maxCount={1} fileList={files[kind] ? [{ uid: kind, name: files[kind]!.name }] : []}
              beforeUpload={file => { setFiles(old => ({ ...old, [kind]: file })); invalidate(); return false }}
              onRemove={() => { setFiles(old => ({ ...old, [kind]: undefined })); invalidate() }}>
              <Button icon={<UploadOutlined />}>选择文件</Button>
            </Upload>
            <Button icon={<DownloadOutlined />} disabled={!baseId || !year || busy} loading={download.isPending && download.variables === kind} onClick={() => download.mutate(kind)}>下载模板</Button>
          </Space>
        </Form.Item>)}
        <Space><Button loading={preview.isPending} disabled={!ready || busy} onClick={() => { invalidate(); preview.mutate() }}>预检</Button>
          <Button type="primary" loading={create.isPending} disabled={!ready || busy || !result?.ok || errors.length > 0} onClick={() => create.mutate()}>创建方案</Button></Space>
      </Form></Card>
      {failure && <Alert type="error" showIcon message={failure} />}
      {errors.length > 0 && <Card title="错误清单"><Table dataSource={errors} rowKey={(_, index) => String(index)} pagination={false} columns={[
        { title: '文件', dataIndex: 'file' }, { title: '行号', dataIndex: 'row', render: row => row ?? '—' }, { title: '内容', dataIndex: 'message' },
      ]} /></Card>}
      {result?.ok && <Alert type="success" showIcon message="预检通过，可以创建方案。" />}
      {result?.summary && <Card title={`预检汇总 · 可生产 ${result.summary.working_days} 天`}>
        <Table rowKey="model" pagination={false} dataSource={Object.entries(result.summary.models).map(([model, values]) => ({ model, ...values, fin0: result.summary.fin0[model] }))} columns={[
          { title: '车型', dataIndex: 'model' }, { title: '全年 PR（台）', dataIndex: 'pr' }, { title: '全年 WS（台）', dataIndex: 'ws' },
          { title: '期初在制（台）', dataIndex: 'initial_wip' }, { title: '期初成品库存（台）', dataIndex: 'fin0' },
        ]} />
      </Card>}
    </Space>
  </>
}

export function NewPlan() {
  return <>
    <PageHeader title="新建排产" subtitle="选择工厂设置，上传计划并预检" />
    <FullImport />
    <SplitImport />
  </>
}
