import { useMemo, useState } from 'react'
import { Alert, App as AntdApp, Button, DatePicker, Descriptions, Divider, Drawer, Input, Select, Space, Steps, Table, Tag, Typography, Upload } from 'antd'
import { DownloadOutlined, RocketOutlined, UploadOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import dayjs, { type Dayjs } from 'dayjs'
import { useNavigate } from 'react-router-dom'
import { ApiError } from '../../api/client'
import { v6Api } from '../../api/v6'
import type { ActualRevision } from '../../types/api'
import type { V6ActualFillingApplyResponse, V6ActualFillingImportIssue, V6ActualFillingPreviewResponse } from '../../types/v6'

type IssueFilters = {
  month?: string
  date?: string
  workshopId?: string
  typeclassId?: string
  errorCode?: string
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function text(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value)
  try {
    return JSON.stringify(value)
  } catch {
    return String(value)
  }
}

function normalizeIssue(value: unknown): V6ActualFillingImportIssue | null {
  const row = asRecord(value)
  if (!row || typeof row.error_code !== 'string') return null
  const nullableText = (field: string): string | null => {
    const current = row[field]
    return typeof current === 'string' && current ? current : null
  }
  return {
    error_code: row.error_code,
    severity: typeof row.severity === 'string' ? row.severity : 'ERROR',
    sheet: nullableText('sheet'),
    cell: nullableText('cell'),
    month: nullableText('month'),
    date: nullableText('date'),
    workshop_id: nullableText('workshop_id'),
    node_id: nullableText('node_id'),
    typeclass_id: nullableText('typeclass_id'),
    field: nullableText('field'),
    actual_value: row.actual_value,
    expected_value: row.expected_value,
    gap: row.gap,
    message: typeof row.message === 'string' ? row.message : row.error_code,
    suggestion: nullableText('suggestion'),
  }
}

function issuesFromError(error: unknown): V6ActualFillingImportIssue[] {
  if (!(error instanceof ApiError)) return []
  const root = asRecord(error.detail)
  const nested = asRecord(root?.detail)
  const values = nested?.issues ?? root?.issues
  return Array.isArray(values)
    ? values.map(normalizeIssue).filter((item): item is V6ActualFillingImportIssue => item !== null)
    : []
}

function optionValues(issues: V6ActualFillingImportIssue[], field: keyof IssueFilters): { value: string; label: string }[] {
  const issueField: keyof V6ActualFillingImportIssue = field === 'workshopId'
    ? 'workshop_id'
    : field === 'typeclassId'
      ? 'typeclass_id'
      : field === 'errorCode'
        ? 'error_code'
        : field
  return Array.from(new Set(issues.map((item) => item[issueField]).filter((value): value is string => typeof value === 'string' && Boolean(value))))
    .sort()
    .map((value) => ({ value, label: value }))
}

function downloadFile(file: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

export function AnnualActualImportDrawer({
  open,
  onClose,
  revisions,
}: {
  open: boolean
  onClose: () => void
  revisions: ActualRevision[]
}) {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [confirmedEffectiveDate, setConfirmedEffectiveDate] = useState('')
  const [supersedesId, setSupersedesId] = useState<string | null>(null)
  const [reason, setReason] = useState('')
  const [preview, setPreview] = useState<V6ActualFillingPreviewResponse | null>(null)
  const [applyResult, setApplyResult] = useState<V6ActualFillingApplyResponse | null>(null)
  const [idempotencyKey, setIdempotencyKey] = useState<string | null>(null)
  const [previewing, setPreviewing] = useState(false)
  const [applying, setApplying] = useState(false)
  const [reportDownloading, setReportDownloading] = useState(false)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [applyRejected, setApplyRejected] = useState(false)
  const [serverIssues, setServerIssues] = useState<V6ActualFillingImportIssue[] | null>(null)
  const [filters, setFilters] = useState<IssueFilters>({})

  const issues = serverIssues || preview?.issues || []
  const filteredIssues = useMemo(() => issues.filter((issue) => (
    (!filters.month || issue.month === filters.month)
    && (!filters.date || issue.date === filters.date)
    && (!filters.workshopId || issue.workshop_id === filters.workshopId)
    && (!filters.typeclassId || issue.typeclass_id === filters.typeclassId)
    && (!filters.errorCode || issue.error_code === filters.errorCode)
  )), [filters, issues])
  const eligibleSupersedes = useMemo(() => {
    const matching = revisions.filter((revision) => (
      revision.schema_version === 2
      && revision.source_formal_pp_id
      && revision.calendar_year
      && (!preview || (
        revision.source_formal_pp_id === preview.source_formal_pp_id
        && revision.calendar_year === preview.calendar_year
      ))
    ))
    const tips = new Map<string, ActualRevision>()
    for (const revision of matching) {
      const key = `${revision.source_formal_pp_id}|${revision.calendar_year}`
      const current = tips.get(key)
      if (!current || `${revision.recorded_at}|${revision.actual_revision_id}` > `${current.recorded_at}|${current.actual_revision_id}`) {
        tips.set(key, revision)
      }
    }
    return Array.from(tips.values()).sort((left, right) => `${right.recorded_at}|${right.actual_revision_id}`.localeCompare(`${left.recorded_at}|${left.actual_revision_id}`))
  }, [preview, revisions])

  const revokePreview = () => {
    setPreview(null)
    setApplyResult(null)
    setIdempotencyKey(null)
    setOperationError(null)
    setApplyRejected(false)
    setServerIssues(null)
    setFilters({})
  }
  const reset = () => {
    setFile(null)
    setConfirmedEffectiveDate('')
    setSupersedesId(null)
    setReason('')
    revokePreview()
  }
  const close = () => {
    reset()
    onClose()
  }
  const changeEffectiveDate = (value: Dayjs | null) => {
    setConfirmedEffectiveDate(value ? value.format('YYYY-MM-DD') : '')
    revokePreview()
  }
  const runPreview = async () => {
    if (!file || !confirmedEffectiveDate) return
    setPreviewing(true)
    setOperationError(null)
    setApplyResult(null)
    setServerIssues(null)
    setApplyRejected(false)
    try {
      const result = await v6Api.previewActualFillingImport({
        file,
        confirmedEffectiveDate,
        supersedesActualRevisionId: supersedesId,
        reason: reason.trim() || undefined,
      })
      setPreview(result)
      setIdempotencyKey(result.outcome === 'PASS' ? crypto.randomUUID() : null)
      message[result.outcome === 'PASS' ? 'success' : 'warning'](
        result.outcome === 'PASS' ? 'Preview 通过，可以人工 Apply' : `Preview 阻断：${result.issues.length} 个问题`,
      )
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : 'Actual Filling Preview 失败')
      const parsedIssues = issuesFromError(error)
      if (parsedIssues.length) setServerIssues(parsedIssues)
    } finally {
      setPreviewing(false)
    }
  }
  const runApply = async () => {
    if (!file || !confirmedEffectiveDate || !preview || preview.outcome !== 'PASS' || !idempotencyKey || !reason.trim()) return
    setApplying(true)
    setOperationError(null)
    setServerIssues(null)
    try {
      const result = await v6Api.applyActualFillingImport({
        file,
        confirmedEffectiveDate,
        supersedesActualRevisionId: supersedesId,
        expectedWorkbookSha256: preview.workbook_sha256,
        expectedPreviewFingerprint: preview.preview_fingerprint,
        reason: reason.trim(),
        idempotencyKey,
      })
      setApplyResult(result)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['actual-revisions'] }),
        queryClient.invalidateQueries({ queryKey: ['v6', 'actual'] }),
      ])
      message.success('ActualRevision V2 已创建；未自动创建 Session 或 Candidate')
    } catch (error) {
      if (!(error instanceof ApiError) || error.status >= 500) {
        try {
          const recovered = await v6Api.actualFillingImportApplication(idempotencyKey)
          setApplyResult(recovered)
          await Promise.all([
            queryClient.invalidateQueries({ queryKey: ['actual-revisions'] }),
            queryClient.invalidateQueries({ queryKey: ['v6', 'actual'] }),
          ])
          message.success('已按幂等键恢复已完成的 ActualRevision V2')
          return
        } catch {
          // The original Apply error remains authoritative when no completed
          // application can be resolved by its idempotency key.
        }
      }
      setOperationError(error instanceof Error ? error.message : 'Actual Filling Apply 失败')
      const parsedIssues = issuesFromError(error)
      if (parsedIssues.length) setServerIssues(parsedIssues)
      if (error instanceof ApiError && (error.status === 409 || error.status === 422)) setApplyRejected(true)
    } finally {
      setApplying(false)
    }
  }
  const downloadErrorReport = async () => {
    if (!file || !confirmedEffectiveDate || !preview) return
    setReportDownloading(true)
    setOperationError(null)
    try {
      const report = await v6Api.downloadActualFillingErrorReport({
        file,
        confirmedEffectiveDate,
        supersedesActualRevisionId: supersedesId,
        expectedWorkbookSha256: preview.workbook_sha256,
        expectedPreviewFingerprint: preview.preview_fingerprint,
        reason: reason.trim() || undefined,
      })
      downloadFile(report)
      message.success(`已下载 ${report.filename}`)
    } catch (error) {
      setOperationError(error instanceof Error ? error.message : '错误报告下载失败')
    } finally {
      setReportDownloading(false)
    }
  }
  const canApply = Boolean(preview?.outcome === 'PASS' && idempotencyKey && reason.trim() && !applyRejected && !applyResult)
  const currentStep = applyResult ? 3 : preview ? 2 : file ? 1 : 0

  return <Drawer title="导入全年 Actual Filling" open={open} onClose={close} width={1120} destroyOnClose>
    <Steps current={currentStep} size="small" items={[
      { title: '选择全年文件' },
      { title: '确认截止日与修订链' },
      { title: 'Preview / 问题定位' },
      { title: 'Apply 完成' },
    ]} />
    <Alert type="info" showIcon style={{ margin: '16px 0' }} message="只接受 V6.1.4 全年 Actual Filling 工作簿" description="Preview 不写业务数据；只有后端全量校验 PASS 后，人工 Apply 才创建一条不可变 ActualRevision V2。" />
    <Space direction="vertical" size={14} style={{ width: '100%' }}>
      <Upload.Dragger
        data-testid="actual-v2-file"
        accept=".xlsx"
        maxCount={1}
        fileList={file ? [{ uid: file.name, name: file.name, status: 'done' }] : []}
        beforeUpload={(nextFile) => {
          setFile(nextFile)
          revokePreview()
          return false
        }}
        onRemove={() => {
          setFile(null)
          revokePreview()
        }}
        disabled={previewing || applying}
      >
        <p className="ant-upload-drag-icon"><UploadOutlined /></p>
        <p className="ant-upload-text">点击或拖入 V6.1.4 全年 Actual Filling XLSX</p>
        <p className="ant-upload-hint">{file ? `${file.name} · ${file.size.toLocaleString()} bytes` : '同一个 File 将用于 Preview、错误报告和 Apply'}</p>
      </Upload.Dragger>
      <Space wrap align="start">
        <div><Typography.Text strong>确认 Actual 截止日 *</Typography.Text><DatePicker data-testid="actual-v2-effective-date" value={confirmedEffectiveDate ? dayjs(confirmedEffectiveDate) : null} onChange={changeEffectiveDate} style={{ width: 180, display: 'block', marginTop: 6 }} /></div>
        <div><Typography.Text strong>替代 ActualRevision V2</Typography.Text><Select allowClear showSearch optionFilterProp="label" data-testid="actual-v2-supersedes" style={{ width: 310, display: 'block', marginTop: 6 }} placeholder="首条 V2 不选择" value={supersedesId || undefined} options={eligibleSupersedes.map((revision) => ({ value: revision.actual_revision_id, label: `${revision.actual_effective_date || revision.effective_date} · ${revision.actual_revision_id.slice(0, 8)} · ${revision.source_formal_pp_id?.slice(0, 8) || '未知 Formal'}` }))} onChange={(value) => { setSupersedesId(value || null); revokePreview() }} /></div>
      </Space>
      <div><Typography.Text strong>导入原因（Apply 必填）*</Typography.Text><Input.TextArea data-testid="actual-v2-reason" value={reason} maxLength={500} showCount rows={2} onChange={(event) => { setReason(event.target.value); revokePreview() }} placeholder="说明 Actual 截止范围及本次修订原因" style={{ marginTop: 6 }} /></div>
      <Space>
        <Button data-testid="actual-v2-preview" type="primary" loading={previewing} disabled={!file || !confirmedEffectiveDate || previewing || applying} onClick={() => void runPreview()}>Preview 全量校验</Button>
        <Button data-testid="actual-v2-apply" loading={applying} disabled={!canApply} onClick={() => void runApply()}>人工 Apply</Button>
        <Button data-testid="actual-v2-error-report" icon={<DownloadOutlined />} loading={reportDownloading} disabled={!preview || !issues.length || reportDownloading} onClick={() => void downloadErrorReport()}>下载错误报告</Button>
      </Space>
      {operationError && <Alert data-testid="actual-v2-operation-error" type="error" showIcon message="操作失败" description={<Space direction="vertical"><span>{operationError}</span>{applyRejected && <span>Preview/并发身份已失效，请重新 Preview 后再 Apply。</span>}</Space>} />}
      {preview && <>
        <Divider style={{ margin: '4px 0' }} />
        <Alert data-testid="actual-v2-preview-outcome" type={preview.outcome === 'PASS' ? 'success' : 'error'} showIcon message={preview.outcome === 'PASS' ? 'Preview PASS' : `Preview BLOCKED · ${preview.issues.length} 个问题`} description={preview.outcome === 'PASS' ? 'Apply 已解锁；后端会重新解析同一个文件并再次执行全部校验。' : '请按 Sheet/单元格定位修正文件，然后重新 Preview。'} />
        <Descriptions data-testid="actual-v2-preview-identity" bordered size="small" column={2} title="工作簿身份（后端解析）">
          <Descriptions.Item label="Schema">{preview.workbook_schema}</Descriptions.Item>
          <Descriptions.Item label="日历年">{preview.calendar_year}</Descriptions.Item>
          <Descriptions.Item label="来源 Formal"><code>{preview.source_formal_pp_id}</code></Descriptions.Item>
          <Descriptions.Item label="Formal 指纹"><code>{preview.source_formal_fingerprint}</code></Descriptions.Item>
          <Descriptions.Item label="工作簿声明截止日">{preview.workbook_declared_effective_date || '未声明'}</Descriptions.Item>
          <Descriptions.Item label="页面确认截止日">{preview.confirmed_effective_date}</Descriptions.Item>
          <Descriptions.Item label="Workbook SHA"><code>{preview.workbook_sha256}</code></Descriptions.Item>
          <Descriptions.Item label="Preview 指纹"><code>{preview.preview_fingerprint}</code></Descriptions.Item>
        </Descriptions>
        <Descriptions bordered size="small" column={2} title="后端覆盖摘要">
          {Object.entries(preview.coverage_summary).map(([key, value]) => <Descriptions.Item key={key} label={key}>{text(value)}</Descriptions.Item>)}
          <Descriptions.Item label="与 supersedes 差异" span={2}>{text(preview.diff_from_superseded_actual)}</Descriptions.Item>
        </Descriptions>
      </>}
      {issues.length > 0 && <>
        <Space wrap data-testid="actual-v2-issue-filters">
          <Select allowClear placeholder="月份" style={{ width: 130 }} options={optionValues(issues, 'month')} value={filters.month} onChange={(value) => setFilters((current) => ({ ...current, month: value }))} />
          <Select allowClear placeholder="日期" style={{ width: 150 }} options={optionValues(issues, 'date')} value={filters.date} onChange={(value) => setFilters((current) => ({ ...current, date: value }))} />
          <Select allowClear placeholder="车间" style={{ width: 140 }} options={optionValues(issues, 'workshopId')} value={filters.workshopId} onChange={(value) => setFilters((current) => ({ ...current, workshopId: value }))} />
          <Select allowClear placeholder="车型" style={{ width: 140 }} options={optionValues(issues, 'typeclassId')} value={filters.typeclassId} onChange={(value) => setFilters((current) => ({ ...current, typeclassId: value }))} />
          <Select allowClear placeholder="错误码" style={{ width: 250 }} options={optionValues(issues, 'errorCode')} value={filters.errorCode} onChange={(value) => setFilters((current) => ({ ...current, errorCode: value }))} />
          <Tag>{filteredIssues.length} / {issues.length}</Tag>
        </Space>
        <Table<V6ActualFillingImportIssue>
          data-testid="actual-v2-issues"
          size="small"
          bordered
          rowKey={(row) => [row.error_code, row.sheet, row.cell, row.date, row.workshop_id, row.node_id, row.typeclass_id, row.field].join('|')}
          dataSource={filteredIssues}
          pagination={{ pageSize: 20, showSizeChanger: true }}
          scroll={{ x: 1600 }}
          columns={[
            { title: '错误码', dataIndex: 'error_code', width: 230, fixed: 'left', render: (value: string, row) => <Space direction="vertical" size={0}><code>{value}</code><Tag color={row.severity === 'ERROR' ? 'error' : 'warning'}>{row.severity}</Tag></Space> },
            { title: '定位', width: 170, render: (_, row) => <Space direction="vertical" size={0}><strong>{row.sheet || '—'} {row.cell || ''}</strong><span>{row.date || row.month || '—'}</span></Space> },
            { title: '范围', width: 220, render: (_, row) => [row.workshop_id, row.node_id, row.typeclass_id, row.field].filter(Boolean).join(' / ') || '—' },
            { title: '实际值', dataIndex: 'actual_value', width: 130, render: text },
            { title: '期望值', dataIndex: 'expected_value', width: 130, render: text },
            { title: '差值', dataIndex: 'gap', width: 110, render: text },
            { title: '问题', dataIndex: 'message', width: 300 },
            { title: '修复建议', dataIndex: 'suggestion', width: 320, render: (value: string | null) => value || '—' },
          ]}
        />
      </>}
      {applyResult && <Alert data-testid="actual-v2-apply-success" type="success" showIcon message="ActualRevision V2 已创建" description={<Space direction="vertical">
        <span>Revision <code>{applyResult.actual_revision_id}</code> · 截止日 {applyResult.actual_effective_date} · 来源 Formal <code>{applyResult.source_formal_pp_id}</code></span>
        <span>本次 Apply 未创建 Session/Candidate；请显式进入 V6.1.4 Rolling 并选择未来完整 Fix 月份。</span>
        <Button data-testid="actual-v2-start-rolling" type="primary" icon={<RocketOutlined />} onClick={() => navigate(`/v6/rolling?actual_revision_id=${encodeURIComponent(applyResult.actual_revision_id)}&source_formal_pp_id=${encodeURIComponent(applyResult.source_formal_pp_id)}`)}>使用此 Actual 开始 V6.1.4 Rolling</Button>
      </Space>} />}
    </Space>
  </Drawer>
}
