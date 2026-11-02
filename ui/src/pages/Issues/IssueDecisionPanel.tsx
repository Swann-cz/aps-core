import { Button, Collapse, Descriptions, Space, Tag, Typography } from 'antd'
import type { PlanningIssue, ActionView } from '../../types/api'

export function IssueDecisionPanel({
  issue,
  previewing,
  applying,
  onPreviewAction,
  onApplyAction,
  onCompare,
  previewResult,
}: {
  issue: PlanningIssue | null
  previewing: boolean
  applying: boolean
  onPreviewAction: (action: ActionView) => void
  onApplyAction: (action: ActionView) => void
  onCompare: () => void
  previewResult: any | null
}) {
  if (!issue) return <div className="muted">从左侧选择一个问题查看决策详情</div>
  const typeclass = (String(issue.scope?.join(' ') || '').match(/typeclass\/([A-Z])/) || [])[1]
  const boundary = boundaryLabel(issue.blocking_boundary)
  return (
    <div className="issue-decision-panel" data-testid="issue-decision-panel">
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="发生了什么">{issue.what_happened || '—'}</Descriptions.Item>
        <Descriptions.Item label="为什么不能自动解决">
          {issue.why || '—'}
          {boundary && <div className="muted" style={{ fontSize: 12 }}>保护边界：{boundary}</div>}
        </Descriptions.Item>
        <Descriptions.Item label="影响范围">
          <Space wrap>
            {(issue.scope || []).map((part) => (
              <Tag key={part}>{scopeLabel(part)}</Tag>
            ))}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="系统已经尝试">
          {(issue.system_tried && issue.system_tried.length ? issue.system_tried : ['无']).map((item) => (
            <div key={item}>· {triedLabel(item)}</div>
          ))}
        </Descriptions.Item>
        <Descriptions.Item label="可选动作">
          <Space wrap>
            {(issue.available_actions || []).map((action) => {
              const label =
                action.action_type === 'ENABLE_WORKING_MODE'
                  ? '预览双班生产'
                  : actionLabel(action.action_type, action.display_name)
              return (
                <Button
                  key={action.action_type}
                  size="small"
                  loading={previewing}
                  onClick={() => onPreviewAction(action)}
                >
                  {label}
                </Button>
              )
            })}
          </Space>
        </Descriptions.Item>
      </Descriptions>
      <Collapse
        ghost
        size="small"
        style={{ marginTop: 8 }}
        items={[{
          key: 'issue-technical',
          label: '技术详情',
          children: (
            <Descriptions column={1} size="small" bordered>
              <Descriptions.Item label="问题类型">{issue.issue_type}</Descriptions.Item>
              <Descriptions.Item label="阻断边界">{issue.blocking_boundary || '—'}</Descriptions.Item>
              <Descriptions.Item label="原始范围">
                <Typography.Text code>{(issue.scope || []).join(' · ') || '—'}</Typography.Text>
              </Descriptions.Item>
              <Descriptions.Item label="问题 ID">
                <Typography.Text code copyable>{issue.issue_id}</Typography.Text>
              </Descriptions.Item>
            </Descriptions>
          ),
        }]}
      />
      {previewResult && (
        <div className="issue-preview-result" style={{ marginTop: 14 }}>
          <div className="muted">
            {previewResult.message || '预览已完成'}
            {typeclass && ` · 车型 ${typeclass}`}
          </div>
          <Space style={{ marginTop: 8 }}>
            <Button onClick={onCompare}>进入版本比对</Button>
          </Space>
        </div>
      )}
    </div>
  )
}

function boundaryLabel(value: string | null | undefined): string {
  if (!value) return ''
  return ({
    ANNUAL_CLOSURE_IMPOSSIBLE: '年度需求无法在当前授权产能内闭合',
    HARD_ENVELOPE_VIOLATION: '违反生产硬边界',
  } as Record<string, string>)[value] ?? '需要计划员处理后才能继续'
}

function scopeLabel(value: string): string {
  if (value.startsWith('month/')) return `月份 ${value.slice(6)}`
  if (value.startsWith('typeclass/')) return `车型 ${value.split('/')[1] || ''}`
  if (value.startsWith('workshop/')) return `车间 ${value.split('/')[1] || ''}`
  return '其他影响范围'
}

function triedLabel(value: string): string {
  return ({
    'rolling closure guard': '检查滚动闭合边界',
    'capacity guard': '检查当前授权产能',
    'V3 daily/block candidate lattice': '尝试日级与生产块候选',
    'bounded repair within authorized scope': '在授权范围内尝试修复',
  } as Record<string, string>)[value] ?? value
}

function actionLabel(actionType: string, displayName: string | null | undefined): string {
  return ({
    ENABLE_SATURDAY: '预览启用周六生产',
    ENABLE_WORKING_MODE: '预览工作模式调整',
    ACCEPT_GAP: '接受当前缺口并调整闭合时间',
    CARRY_OVER: '申请跨年结转',
  } as Record<string, string>)[actionType] ?? String(displayName || '查看可选动作')
}
