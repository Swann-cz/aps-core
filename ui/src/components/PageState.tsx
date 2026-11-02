import { Alert, Button, Empty } from 'antd'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function PageSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="page-skeleton" data-testid="page-skeleton">
      {Array.from({ length: rows }, (_, index) => (
        <div key={index} className="page-skeleton-row" />
      ))}
    </div>
  )
}

function ReasonList({ values }: { values: string[] }) {
  return (
    <ul className="page-state-reasons">
      {values.map((reason) => (
        <li key={reason}>{reason}</li>
      ))}
    </ul>
  )
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    return `${error.message}${error.status ? `（HTTP ${error.status}）` : ''}`
  }
  if (error instanceof Error) return error.message
  return '未知错误'
}

export type PageStateProps =
  | { kind: 'loading'; rows?: number }
  | { kind: 'empty'; title: string; action?: ReactNode }
  | { kind: 'business-blocked'; title: string; reasons: string[]; action?: ReactNode }
  | { kind: 'system-error'; error: unknown; onRetry?: () => void }
  | { kind: 'confirmed-readonly'; label?: string }
  | { kind: 'stale-revision'; onRefresh: () => void }

export function PageState(props: PageStateProps) {
  if (props.kind === 'loading') return <PageSkeleton rows={props.rows ?? 5} />
  if (props.kind === 'empty')
    return <Empty description={props.title}>{props.action}</Empty>
  if (props.kind === 'business-blocked')
    return (
      <Alert
        type="warning"
        showIcon
        message={props.title}
        description={<ReasonList values={props.reasons} />}
        action={props.action}
      />
    )
  if (props.kind === 'confirmed-readonly')
    return <Alert type="info" message={props.label || '已确认版本，只读'} />
  if (props.kind === 'stale-revision')
    return (
      <Alert
        type="warning"
        message="计划已发生变化"
        action={
          <Button onClick={props.onRefresh}>刷新最新计划</Button>
        }
      />
    )
  return (
    <Alert
      type="error"
      showIcon
      message="系统请求失败"
      description={errorMessage(props.error)}
      action={props.onRetry ? <Button onClick={props.onRetry}>重试</Button> : null}
    />
  )
}
