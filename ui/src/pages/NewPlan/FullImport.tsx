import { useState } from 'react'
import { Alert, App, Button, Card, Form, Input, Select, Space, Table, Upload } from 'antd'
import { DownloadOutlined, UploadOutlined } from '@ant-design/icons'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { core, FullPlanImportError, type FullImportError, type FullPlanPreview } from '../../api/core'
import { useCore } from '../../app/CoreContext'

export function FullImport({ wizard = false, onCreated, onChecked }: { wizard?: boolean; onCreated?: () => void; onChecked?: (ok: boolean) => void }) {
  const state = useCore()
  const navigate = useNavigate()
  const { message } = App.useApp()
  const [year, setYear] = useState(String(new Date().getFullYear()))
  const [baseId, setBaseId] = useState<string>()
  const [file, setFile] = useState<File>()
  const [result, setResult] = useState<FullPlanPreview | null>(null)
  const [errors, setErrors] = useState<FullImportError[]>([])
  const [failure, setFailure] = useState('')
  const invalidate = () => { setResult(null); setErrors([]); setFailure(''); onChecked?.(false) }
  const payload = (selected = file!) => {
    const data = new FormData()
    data.append('file', selected)
    return data
  }
  const onError = (error: Error) => {
    onChecked?.(false); setResult(null); setFailure(error.message)
    setErrors(error instanceof FullPlanImportError ? error.errors : [])
  }
  const preview = useMutation({ mutationFn: (selected: File) => core.previewFullPlan(payload(selected)), onSuccess: data => {
    setResult(data); setErrors(data.errors)
    setFailure(data.ok ? '' : '预检未通过，请修改模板后重新上传。')
    onChecked?.(data.ok)
  }, onError })
  const create = useMutation({ mutationFn: () => core.createFullPlan(payload()), onSuccess: summary => {
    state.update(summary); state.select(summary.id)
    void message.success('方案已创建，尚未运行。')
    if (onCreated) onCreated()
    else navigate('/planning-conditions')
  }, onError })
  const download = useMutation({ mutationFn: () => core.template('full', baseId, year), onSuccess: blob => {
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url; link.download = `一键导入模板-${year}.xlsx`
    document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url)
  }, onError: (error: Error) => { void message.error(error.message) } })
  const busy = preview.isPending || create.isPending
  const chooseFile = (value: File) => { setFile(value); invalidate(); preview.mutate(value); return false as const }
  return <Card title={wizard ? '第 1 步 · 导入' : '一键导入'}>
    <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <Form layout="vertical" disabled={busy} style={{ maxWidth: 760 }}>
        <Form.Item label="模板年份" required>
          <Input aria-label="模板年份" type="number" value={year} disabled={download.isPending} style={{ width: 110 }} onChange={event => setYear(event.target.value)} />
        </Form.Item>
        <Form.Item label="预填来源方案" extra="可选；选了就照抄该方案的工厂参数和期初在制，不选则这些格留空，由填表人填写。">
          <Select allowClear value={baseId} disabled={download.isPending} loading={state.list.isLoading} placeholder="不预填（空白模板）" options={state.scenarios.map(s => ({ value: s.id, label: s.name }))} onChange={setBaseId} />
        </Form.Item>
        <Form.Item>
          <Button icon={<DownloadOutlined />} loading={download.isPending} disabled={!year || busy} onClick={() => download.mutate()}>下载模板</Button>
        </Form.Item>
        <Form.Item label="完整排产文件" required extra="上传一个填写完成的 xlsx 文件，方案名称和计划期在模板中填写。">
          <Upload.Dragger accept=".xlsx" maxCount={1} disabled={busy} fileList={file ? [{ uid: 'full', name: file.name }] : []}
            beforeUpload={chooseFile} onRemove={() => { setFile(undefined); invalidate() }}>
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p className="ant-upload-text">点击或拖入填写好的 xlsx，自动检查</p>
          </Upload.Dragger>
        </Form.Item>
        {failure ? <Upload accept=".xlsx" showUploadList={false} disabled={busy} beforeUpload={chooseFile}><Button type="primary" className={wizard ? 'wizard-primary' : undefined} disabled={busy}>重新选择文件</Button></Upload> : <Button type="primary" className={wizard ? 'wizard-primary' : undefined} loading={busy} disabled={!file || busy || !result?.ok || errors.length > 0} onClick={() => create.mutate()}>{wizard ? '创建方案，下一步' : '创建方案'}</Button>}
      </Form>
      {!file && <Alert type="info" showIcon message="下载模板并填写，选好文件即自动预检。" />}
      {preview.isPending && <Alert type="info" showIcon message="正在检查文件…" />}
      {failure && <Alert type="error" showIcon message={failure} />}
      {errors.length > 0 && <Table dataSource={errors} rowKey={(_, index) => String(index)} pagination={false} scroll={{ x: 600 }} columns={[
        { title: '工作表', dataIndex: 'sheet' }, { title: '行', dataIndex: 'row', render: row => row ?? '—' },
        { title: '列', dataIndex: 'column', render: column => column ?? '—' }, { title: '说明', dataIndex: 'message' },
      ]} />}
      {result?.ok && errors.length === 0 && <Alert type="success" showIcon message="预检通过，可以创建方案。" />}
      {result?.summary && <Card size="small" title={`预检汇总 · 可生产 ${result.summary.working_days} 天`}>
        <Table rowKey="model" pagination={false} scroll={{ x: 650 }} dataSource={Object.entries(result.summary.models).map(([model, values]) => ({ model, ...values, fin0: result.summary.fin0[model] }))} columns={[
          { title: '车型', dataIndex: 'model' }, { title: '全年需求（台）', dataIndex: 'pr' }, { title: '全年交付（台）', dataIndex: 'ws' },
          { title: '期初在制（台）', dataIndex: 'initial_wip' }, { title: '期初成品库存（台）', dataIndex: 'fin0' },
        ]} />
        {/* TODO(边界): 预检接口不返回条件数，创建后读取 conditions；不在前端解析工作簿。 */}
        <p>带入的条件数将在创建方案后的“排产条件”步骤显示。</p>
      </Card>}
    </Space>
  </Card>
}
