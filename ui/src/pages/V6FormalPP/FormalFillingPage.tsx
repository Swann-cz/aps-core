import { Alert, App as AntdApp, Button, Select, Space, Tag } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { rememberFormalId } from '../../utils/v6FormalViewAuthority'
import { V6FillingProjectionView } from '../V6CandidateWorkbench/CandidateFillingPanel'

export function FormalFillingPage() {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const { formalPpId = '' } = useParams()
  const [searchParams, setSearchParams] = useSearchParams()
  const [exporting, setExporting] = useState(false)
  const [exportError, setExportError] = useState<string | null>(null)
  const [lastExportFilename, setLastExportFilename] = useState<string | null>(null)
  const [annualExportYear, setAnnualExportYear] = useState<number | null>(null)
  const [annualExporting, setAnnualExporting] = useState(false)
  const [annualExportError, setAnnualExportError] = useState<string | null>(null)
  const [lastAnnualExportFilename, setLastAnnualExportFilename] = useState<string | null>(null)
  const annualQuery = useQuery({
    queryKey: ['v6', 'formal-annual', formalPpId],
    queryFn: () => v6Api.formalAnnualOverview(formalPpId),
    enabled: Boolean(formalPpId),
    retry: false,
  })
  const months = (annualQuery.data?.months || []).map((item) => item.month)
  const formalYears = Array.from(new Set(months.map((item) => Number(item.slice(0, 4))).filter(Number.isInteger))).sort((left, right) => left - right)
  const requestedMonth = searchParams.get('month')
  const month = requestedMonth || months[0] || ''
  const fillingQuery = useQuery({
    queryKey: ['v6', 'formal-filling', formalPpId, month],
    queryFn: () => v6Api.formalMonthlyFilling(formalPpId, month),
    enabled: Boolean(formalPpId && month),
    retry: false,
  })
  const annualIdentityValid = Boolean(
    annualQuery.data
    && annualQuery.data.source_kind === 'FORMAL_PP'
    && annualQuery.data.read_only === true
    && annualQuery.data.formal_pp_id === formalPpId,
  )
  useEffect(() => {
    if (annualQuery.data && annualIdentityValid) rememberFormalId(annualQuery.data.formal_pp_id)
  }, [annualIdentityValid, annualQuery.data])
  useEffect(() => {
    if (!requestedMonth && month) {
      const next = new URLSearchParams(searchParams)
      next.set('month', month)
      setSearchParams(next, { replace: true })
    }
  }, [month, requestedMonth, searchParams, setSearchParams])
  useEffect(() => {
    setExportError(null)
    setLastExportFilename(null)
  }, [formalPpId, month])
  useEffect(() => {
    const monthYear = Number(month.slice(0, 4))
    setAnnualExportYear((current) => {
      if (current && formalYears.includes(current)) return current
      if (Number.isInteger(monthYear) && formalYears.includes(monthYear)) return monthYear
      return formalYears[0] || null
    })
  }, [formalPpId, month, formalYears.join('|')])
  useEffect(() => {
    setAnnualExportError(null)
    setLastAnnualExportFilename(null)
  }, [formalPpId, annualExportYear])
  if (!formalPpId) return <PageState kind="business-blocked" title="缺少 Formal PP ID" reasons={['请从正式 PP 库选择版本。']} />
  if (annualQuery.isLoading || (month && fillingQuery.isLoading)) return <PageState kind="loading" rows={8} />
  if (annualQuery.isError) return <PageState kind="system-error" error={annualQuery.error} onRetry={() => void annualQuery.refetch()} />
  if (!annualQuery.data) return <PageState kind="empty" title="后端未提供 Formal 年度投影" />
  if (!annualIdentityValid) return <PageState kind="system-error" error={new Error('Formal 年度投影身份不一致，已停止展示。')} />
  if (months.length === 0) return <PageState kind="empty" title="Formal 年度投影没有可查看月份" />
  if (fillingQuery.isError) return <PageState kind="system-error" error={fillingQuery.error} onRetry={() => void fillingQuery.refetch()} />
  if (!fillingQuery.data) return <PageState kind="empty" title="后端未提供 Formal 月度 Filling 投影" />
  const annual = annualQuery.data
  const filling = fillingQuery.data
  if (
    filling.source_kind !== 'FORMAL_PP'
    || filling.read_only !== true
    || filling.formal_pp_id !== annual.formal_pp_id
    || filling.formal_fingerprint !== annual.formal_fingerprint
    || filling.month !== month
  ) {
    return <PageState kind="system-error" error={new Error('Formal Annual 与 Filling 身份、指纹或月份不一致，已停止展示。')} />
  }
  const downloadFilling = async () => {
    setExporting(true)
    setExportError(null)
    setLastExportFilename(null)
    try {
      const file = await v6Api.exportFormalMonthlyFilling(formalPpId, month)
      const url = URL.createObjectURL(file.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setLastExportFilename(file.filename)
      message.success(`已下载 ${file.filename}`)
    } catch (error) {
      const detail = error instanceof Error ? error.message : '导出 Formal Filling 失败'
      setExportError(detail)
      message.error(detail)
    } finally {
      setExporting(false)
    }
  }
  const downloadAnnualFilling = async () => {
    if (!annualExportYear || !formalYears.includes(annualExportYear)) return
    setAnnualExporting(true)
    setAnnualExportError(null)
    setLastAnnualExportFilename(null)
    try {
      const file = await v6Api.exportFormalAnnualFilling(formalPpId, annualExportYear)
      const url = URL.createObjectURL(file.blob)
      const link = document.createElement('a')
      link.href = url
      link.download = file.filename
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      setLastAnnualExportFilename(file.filename)
      message.success(`已下载 ${file.filename}`)
    } catch (error) {
      const detail = error instanceof Error ? error.message : '导出全年 Formal Filling 失败'
      setAnnualExportError(detail)
      message.error(detail)
    } finally {
      setAnnualExporting(false)
    }
  }
  const changeMonth = (value: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('month', value)
    setSearchParams(next)
  }
  return <div className="page-container">
    <PageHeader
      title="月度 Filling"
      subtitle={`V6.1.4 正式 PP（只读） · ${annual.display_name}`}
      actions={<Space wrap><Button icon={<DownloadOutlined />} loading={exporting} disabled={!month || exporting} onClick={() => void downloadFilling()}>导出 Filling</Button><Select aria-label="全年 Filling 年份" style={{ width: 104 }} value={annualExportYear ?? undefined} options={formalYears.map((year) => ({ value: year, label: `${year} 年` }))} onChange={setAnnualExportYear} /><Button data-testid="formal-annual-filling-export" icon={<DownloadOutlined />} loading={annualExporting} disabled={!annualIdentityValid || !annualExportYear || !formalYears.includes(annualExportYear) || annualExporting} onClick={() => void downloadAnnualFilling()}>导出全年 Filling</Button><Button onClick={() => navigate('/v6/formal-pp')}>切换正式 PP</Button><Button onClick={() => navigate(`/v6/formal-pp/${encodeURIComponent(formalPpId)}/annual`)}>年度总览</Button></Space>}
    />
    {lastExportFilename && <Alert type="success" showIcon style={{ marginBottom: 14 }} message="Filling 导出成功" description={lastExportFilename} />}
    {exportError && <Alert type="error" showIcon style={{ marginBottom: 14 }} message="Filling 导出失败" description={exportError} />}
    {lastAnnualExportFilename && <Alert data-testid="formal-annual-filling-export-success" type="success" showIcon style={{ marginBottom: 14 }} message="全年 Filling 导出成功" description={lastAnnualExportFilename} />}
    {annualExportError && <Alert data-testid="formal-annual-filling-export-error" type="error" showIcon style={{ marginBottom: 14 }} message="全年 Filling 导出失败" description={annualExportError} />}
    <Space wrap style={{ marginBottom: 14 }}>
      <Tag color="blue">Formal · 只读</Tag>
      <Tag>保存于 {annual.saved_at}</Tag>
      <Tag>来源 Candidate {annual.source_candidate_id.slice(0, 8)}</Tag>
      <Tag>指纹 {annual.formal_fingerprint.slice(0, 12)}</Tag>
    </Space>
    <V6FillingProjectionView
      filling={filling}
      identity={{
        kind: 'FORMAL_PP',
        sourceId: annual.formal_pp_id,
        displayName: annual.display_name,
        savedAt: annual.saved_at,
        sourceCandidateId: annual.source_candidate_id,
        fingerprint: annual.formal_fingerprint,
        readOnly: true,
      }}
      months={months}
      month={month}
      onMonthChange={changeMonth}
    />
  </div>
}
