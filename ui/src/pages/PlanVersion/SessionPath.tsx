import { Steps, Tag } from 'antd'
import { shortId } from '../../utils/format'
import type { PlanHistory } from '../../types/api'

export function SessionPath({ versions }: { versions: PlanHistory[] }) {
  if (versions.length === 0) return <div className="muted">当前会话没有版本路径</div>
  const ordered = [...versions].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)))
  return (
    <div className="session-path" data-testid="session-path">
      <Steps
        size="small"
        direction="vertical"
        current={ordered.length - 1}
        items={ordered.map((version) => ({
          title: (
            <span>
              {version.display_name || shortId(version.plan_version_id)}
              <Tag style={{ marginLeft: 6 }}>{statusLabel(version.status)}</Tag>
            </span>
          ),
          description: <span className="muted">{shortId(version.plan_version_id)}</span>,
        }))}
      />
    </div>
  )
}

function statusLabel(status: string): string {
  return ({ PROPOSED: '待确认', CONFIRMED: '已确认', SUPERSEDED: '历史版本' } as Record<string, string>)[status] ?? '后端状态'
}
