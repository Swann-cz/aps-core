import { Tag } from 'antd'

const colorMap: Record<string, string> = {
  CONFIRMED: 'green',
  PROPOSED: 'blue',
  READY_TO_CONFIRM: 'green',
  ATTENTION_REQUIRED: 'orange',
  PASS: 'green',
  OK: 'green',
  HEALTHY: 'green',
  LOCKED: 'gold',
  MUTABLE: 'blue',
  WORKING: 'green',
  REST: 'default',
  ACTUALIZED: 'green',
  NO_DATA: 'default',
  NOT_SELECTED: 'default',
  SUPERSEDED: 'orange',
  ACTIVE: 'blue',
}

const labelMap: Record<string, string> = {
  CONFIRMED: 'CONFIRMED / 已确认',
  PROPOSED: 'PROPOSED / 待确认',
  READY_TO_CONFIRM: 'READY_TO_CONFIRM / 可确认',
  ATTENTION_REQUIRED: 'ATTENTION_REQUIRED / 需关注',
  PASS: 'PASS / 通过',
  OK: 'OK / 健康',
  LOCKED: 'LOCKED / 已锁定',
  MUTABLE: 'MUTABLE / 可调整',
  WORKING: 'WORKING / 工作日',
  REST: 'REST / 休息日',
  ACTUALIZED: 'ACTUALIZED / 已实际发生',
  NO_DATA: 'NO_DATA / 无数据',
  ACTIVE: 'ACTIVE / 当前激活',
  SUPERSEDED: 'SUPERSEDED / 已被替代',
}

export function StatusTag({ value, short = false }: { value: string | null | undefined; short?: boolean }) {
  const text = value || '—'
  return <Tag color={colorMap[text]}>{short ? text : labelMap[text] || text}</Tag>
}
