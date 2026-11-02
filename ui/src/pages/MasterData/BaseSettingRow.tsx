import { Button, Space } from 'antd'
import type { ReactNode } from 'react'
import { StatusTag } from '../../components/StatusTag'
import { formatDateTime } from '../../utils/format'

export type BaseSettingRowProps = {
  title: string
  ready: boolean
  versionName: string | null
  updatedAt: string | null
  summary: ReactNode
  onView: () => void
  onEdit: () => void
  onHistory: () => void
}

export function BaseSettingRow(props: BaseSettingRowProps) {
  return (
    <section className="base-setting-row">
      <StatusTag value={props.ready ? 'READY' : 'BLOCKED'} />
      <div className="base-setting-main">
        <strong>{props.title}</strong>
        <div className="base-setting-summary">{props.summary}</div>
      </div>
      <div className="base-setting-version">
        {props.versionName || '未配置'}
        {props.updatedAt ? <small>{formatDateTime(props.updatedAt)}</small> : null}
      </div>
      <Space>
        <Button onClick={props.onView}>查看</Button>
        <Button onClick={props.onEdit}>修改</Button>
        <Button type="link" onClick={props.onHistory}>
          查看历史
        </Button>
      </Space>
    </section>
  )
}
