import { Button, Space, Tag } from 'antd'
import { ReloadOutlined } from '@ant-design/icons'
import { useV6Planning } from '../app/V6PlanningContext'

export function V6ContextBar() {
  const state = useV6Planning()
  const session = state.activeSession
  const candidate = state.workbench?.current_candidate
  if (state.multipleOpenSessions) {
    return <Tag color="error">检测到多个开放 V6.1.4 Session，请先处理数据冲突</Tag>
  }
  if (!session) return <span className="header-plan-label">V6.1.4 · 当前无进行中的排产</span>
  return (
    <Space size={8} wrap>
      <strong>{session.generation_mode === 'INITIAL_FROM_ZERO' ? 'V6.1.4 初始排产' : 'V6.1.4 Rolling'}</strong>
      <Tag color="processing">{session.status}</Tag>
      <Tag>Session {session.session_id.slice(0, 8)}</Tag>
      <Tag>rev.{session.planning_revision}</Tag>
      <Tag color={candidate ? 'blue' : undefined}>{candidate ? `Draft #${candidate.candidate_revision}` : '尚未生成候选'}</Tag>
      <Button size="small" type="text" icon={<ReloadOutlined spin={state.fetching} />} onClick={() => void state.refresh()}>刷新</Button>
    </Space>
  )
}
