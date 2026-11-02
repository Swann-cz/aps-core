import { Descriptions, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'

export function SystemDiagnostics() {
  const stateQuery = useQuery({
    queryKey: ['workbench-state'],
    queryFn: () => api.workbenchState(),
  })

  if (stateQuery.isLoading) return <PageState kind="loading" rows={4} />
  return (
    <div>
      <PageHeader title="系统诊断" subtitle="只读信息：连接、版本与状态；无任何可切换开关" />
      <Descriptions column={1} size="small" bordered style={{ maxWidth: 720 }}>
        <Descriptions.Item label="API 连接">
          {stateQuery.error ? (
            <Tag color="red">不可达</Tag>
          ) : (
            <Tag color="green">正常</Tag>
          )}
        </Descriptions.Item>
        <Descriptions.Item label="前端构建版本">
          <code>V5 workbench（React 18 + Vite）</code>
        </Descriptions.Item>
        <Descriptions.Item label="后端契约版本">
          <code>API_CONTRACT_V1 §9（V5 additive）</code>
        </Descriptions.Item>
        <Descriptions.Item label="当前计划">
          {stateQuery.data?.plan_display || '—'}
        </Descriptions.Item>
        <Descriptions.Item label="会话/版本">
          {stateQuery.data?.session_id
            ? `${String(stateQuery.data.session_id).slice(0, 8)}… / rev.${stateQuery.data.planning_revision}`
            : '无会话'}
        </Descriptions.Item>
        <Descriptions.Item label="最近请求错误">
          {stateQuery.error ? String(stateQuery.error) : '无'}
        </Descriptions.Item>
      </Descriptions>
    </div>
  )
}
