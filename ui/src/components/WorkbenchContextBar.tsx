import { InfoCircleOutlined, WarningOutlined } from '@ant-design/icons'
import { Button, Popover, Space, Tag } from 'antd'
import type { WorkbenchState } from '../types/api'
import { PlannerStateTag } from './PlannerStateTag'
import { StatusTag } from './StatusTag'

export function WorkbenchContextBar({ state }: { state: WorkbenchState }) {
  return (
    <div className="workbench-context-bar">
      <strong>
        {state.plan_display || `${state.planning_year || ''} 年度计划` || '未命名计划'}
      </strong>
      <span className="workbench-context-factory">{state.factory_name || '未选择工厂'}</span>
      <StatusTag value={state.version_status || state.plan_status} />
      <PlannerStateTag value={state.planner_state} fallback={state.version_status} />
      <Button type="text" size="small" icon={<WarningOutlined />}>
        问题 {state.outstanding_issue_count ?? 0}
      </Button>
      <Popover
        content={
          <Space direction="vertical" size={4}>
            <Tag>会话 {state.session_id ? state.session_id.slice(0, 8) : '—'}</Tag>
            <Tag>版本 {state.current_plan_version_id ? state.current_plan_version_id.slice(0, 8) : '—'}</Tag>
            <Tag>rev.{state.planning_revision ?? 0}</Tag>
          </Space>
        }
        title="技术信息"
        trigger="hover"
      >
        <Button type="text" size="small" icon={<InfoCircleOutlined />} />
      </Popover>
    </div>
  )
}
