import { Alert, Empty, Spin } from 'antd'
import type { ReactNode } from 'react'
import { ApiError } from '../api/client'

export function QueryLoading({ label = '正在读取后端数据…' }: { label?: string }) {
  return <div className="query-state"><Spin /><span>{label}</span></div>
}

export function QueryError({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof ApiError
    ? `${error.message}${error.status ? `（HTTP ${error.status}）` : ''}`
    : error instanceof Error ? error.message : '读取后端数据失败'
  return <Alert type="error" showIcon message="后端请求失败" description={message} action={onRetry ? <a onClick={onRetry}>重试</a> : undefined} />
}

export function QueryEmpty({ description = '后端没有返回数据' }: { description?: ReactNode }) {
  return <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={description} />
}
