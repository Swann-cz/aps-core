import { List, Tag } from 'antd'
import { StatusTag } from '../../components/StatusTag'
import type { PlanningIssue } from '../../types/api'

export function issueBusinessName(issue: PlanningIssue, workshopForTypeclass: Record<string, string>): string {
  const scope = String(issue.scope?.join(' ') || '')
  const typeclass = (scope.match(/typeclass\/([A-Z])/) || [])[1]
  const workshop = typeclass ? workshopForTypeclass[typeclass] || typeclass : null
  if (issue.issue_type.includes('CLOSURE') || issue.issue_type.includes('GAP')) {
    return `${workshop || ''} 容量缺口`.trim()
  }
  return String(issue.what_happened || '待处理问题').slice(0, 24)
}

export function IssueQueue({
  issues,
  selectedId,
  workshopForTypeclass,
  onSelect,
}: {
  issues: PlanningIssue[]
  selectedId: string | null
  workshopForTypeclass: Record<string, string>
  onSelect: (issue: PlanningIssue) => void
}) {
  return (
    <div className="issue-queue" data-testid="issue-queue">
      <List
        size="small"
        dataSource={issues}
        renderItem={(issue) => {
          const name = issueBusinessName(issue, workshopForTypeclass)
          const dateRange = issue.scope?.find((part) => part.startsWith('month/'))?.replace('month/', '') || ''
          return (
            <List.Item
              className={issue.issue_id === selectedId ? 'issue-queue-item selected' : 'issue-queue-item'}
              onClick={() => onSelect(issue)}
            >
              <div>
                <strong>{name}</strong>
                <div className="muted" style={{ fontSize: 12 }}>
                  {dateRange && <Tag style={{ marginRight: 4 }}>{dateRange}</Tag>}
                  {String(issue.what_happened || '').slice(0, 56)}
                </div>
              </div>
              <StatusTag value={issue.status} short />
            </List.Item>
          )
        }}
      />
    </div>
  )
}
