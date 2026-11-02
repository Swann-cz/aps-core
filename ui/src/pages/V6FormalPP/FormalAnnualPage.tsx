import { Button, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { rememberFormalId } from '../../utils/v6FormalViewAuthority'
import { V6AnnualProjectionView } from '../V6CandidateWorkbench/CandidateAnnualPanel'

export function FormalAnnualPage() {
  const navigate = useNavigate()
  const { formalPpId = '' } = useParams()
  const query = useQuery({
    queryKey: ['v6', 'formal-annual', formalPpId],
    queryFn: () => v6Api.formalAnnualOverview(formalPpId),
    enabled: Boolean(formalPpId),
    retry: false,
  })
  const identityValid = Boolean(
    query.data
    && query.data.source_kind === 'FORMAL_PP'
    && query.data.read_only === true
    && query.data.formal_pp_id === formalPpId,
  )
  useEffect(() => {
    if (query.data && identityValid) rememberFormalId(query.data.formal_pp_id)
  }, [identityValid, query.data])
  if (!formalPpId) return <PageState kind="business-blocked" title="缺少 Formal PP ID" reasons={['请从正式 PP 库选择版本。']} />
  if (query.isLoading) return <PageState kind="loading" rows={8} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  if (!query.data) return <PageState kind="empty" title="后端未提供 Formal 年度投影" />
  if (!identityValid) return <PageState kind="system-error" error={new Error('Formal 年度投影身份不一致，已停止展示。')} />
  const annual = query.data
  return <div className="page-container">
    <PageHeader
      title="年度总览"
      subtitle={`V6.1.4 正式 PP（只读） · ${annual.display_name}`}
      actions={<Space><Button onClick={() => navigate('/v6/formal-pp')}>切换正式 PP</Button><Button type="primary" onClick={() => navigate(`/v6/formal-pp/${encodeURIComponent(formalPpId)}/filling`)}>月度 Filling</Button></Space>}
    />
    <Space wrap style={{ marginBottom: 14 }}>
      <Tag color="blue">Formal · 只读</Tag>
      <Tag>保存于 {annual.saved_at}</Tag>
      <Tag>来源 Candidate {annual.source_candidate_id.slice(0, 8)}</Tag>
      <Tag>指纹 {annual.formal_fingerprint.slice(0, 12)}</Tag>
    </Space>
    <V6AnnualProjectionView
      annual={annual}
      identity={{
        kind: 'FORMAL_PP',
        sourceId: annual.formal_pp_id,
        displayName: annual.display_name,
        savedAt: annual.saved_at,
        sourceCandidateId: annual.source_candidate_id,
        fingerprint: annual.formal_fingerprint,
        readOnly: true,
      }}
      issueCount={annual.hard_error_codes.length + annual.warning_codes.length}
      onOpenMonth={(month) => navigate(`/v6/formal-pp/${encodeURIComponent(formalPpId)}/filling?month=${encodeURIComponent(month)}`)}
    />
  </div>
}
