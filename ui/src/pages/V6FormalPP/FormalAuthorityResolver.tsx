import { App as AntdApp, Button } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Navigate, useLocation, useNavigate, useSearchParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageState } from '../../components/PageState'
import {
  clearRecentFormalId,
  latestFormalVersion,
  readRecentFormalId,
} from '../../utils/v6FormalViewAuthority'

export function FormalAuthorityResolver({ view }: { view: 'annual' | 'filling' }) {
  const { message } = AntdApp.useApp()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const query = useQuery({
    queryKey: ['v6', 'formal'],
    queryFn: v6Api.formalVersions,
    retry: false,
  })
  const staleNoticeShown = useRef(false)
  const versions = query.data || []
  const explicit = searchParams.get('formal_pp_id')
  const recentId = readRecentFormalId()
  const recent = recentId
    ? versions.find((item) => item.formal_pp_id === recentId) || null
    : null
  const latest = latestFormalVersion(versions)
  const staleRecent = Boolean(!explicit && recentId && !recent)
  useEffect(() => {
    if (!query.isSuccess || !staleRecent || staleNoticeShown.current) return
    staleNoticeShown.current = true
    clearRecentFormalId()
    if (latest) message.info('最近查看的 Formal PP 已不存在，已切换到最新正式版本。')
  }, [latest, message, query.isSuccess, staleRecent])
  const v5PlanId = searchParams.get('plan_version_id')
  if (v5PlanId) {
    const target = view === 'annual' ? '/v5/annual-overview' : '/v5/monthly-filling'
    return <Navigate replace to={`${target}${location.search}`} />
  }
  if (query.isLoading) return <PageState kind="loading" rows={6} />
  if (query.isError) return <PageState kind="system-error" error={query.error} onRetry={() => void query.refetch()} />
  const selected = explicit
    ? versions.find((item) => item.formal_pp_id === explicit) || null
    : recent || latest
  if (explicit && !selected) {
    return <PageState
      kind="business-blocked"
      title="指定的 V6.1.4 正式 PP 不存在"
      reasons={[`Formal PP：${explicit}`, '系统不会静默切换到其他正式版本。']}
      action={<Button onClick={() => navigate('/v6/formal-pp')}>打开正式 PP 库</Button>}
    />
  }
  if (!selected) {
    return <PageState
      kind="empty"
      title="尚无 V6.1.4 正式 PP；年度总览和月度 Filling 不会回退显示 V5 数据。"
      action={<Button type="primary" onClick={() => navigate('/p00-setup')}>开始 V6.1.4 排产</Button>}
    />
  }
  const nextParams = new URLSearchParams(searchParams)
  nextParams.delete('formal_pp_id')
  nextParams.delete('plan_version_id')
  const queryString = nextParams.toString()
  const target = `/v6/formal-pp/${encodeURIComponent(selected.formal_pp_id)}/${view}${queryString ? `?${queryString}` : ''}`
  return <Navigate replace to={target} />
}
