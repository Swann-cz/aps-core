import { useState } from 'react'
import { Button, Drawer, InputNumber, Space, Spin, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import type { MonthlyDay, ScalarValue } from '../../types/api'
import { displayValue } from '../../utils/format'

export function CellInspectorDrawer({
  planVersionId,
  day,
  objectRef,
  fieldLabel,
  value,
  editable,
  onClose,
  onDraftChange,
}: {
  planVersionId: string
  day: MonthlyDay | null
  objectRef: string | null
  fieldLabel: string
  value: ScalarValue | null
  editable: boolean
  onClose: () => void
  onDraftChange: (next: number | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const [draftValue, setDraftValue] = useState<number | null>(typeof value === 'number' ? value : null)
  const open = Boolean(day && objectRef)
  const dateLabel = day ? `${Number(day.date.slice(5, 7))}月${Number(day.date.slice(8))}日` : ''
  const explanationQuery = useQuery({
    queryKey: ['explanation', planVersionId, objectRef],
    queryFn: () => api.explanation(planVersionId, objectRef as string),
    enabled: open,
  })

  const whyLines = explanationQuery.data
    ? [
        explanationQuery.data.headline,
        explanationQuery.data.decision,
        ...(explanationQuery.data.reason_chain || []),
        ...(explanationQuery.data.hard_constraints || []),
        ...(explanationQuery.data.business_intents || []),
        ...(explanationQuery.data.applied_effects || []),
      ].filter(Boolean)
    : []

  return (
    <Drawer
      data-testid="cell-inspector-drawer"
      title={`${fieldLabel}，${dateLabel}`}
      open={open}
      onClose={onClose}
      width={460}
    >
      {explanationQuery.isLoading && <Spin />}
      <section className="cell-inspector-why">
        <h4>为什么是 {displayValue(value)}</h4>
        {whyLines.length > 0 ? (
          <ul className="page-state-reasons">
            {whyLines.slice(0, 12).map((line: string, index: number) => (
              <li key={index}>{line}</li>
            ))}
          </ul>
        ) : (
          <div className="muted">后端未返回该单元格的解释</div>
        )}
      </section>
      {editable && (
        <section style={{ marginTop: 16 }}>
          {editing ? (
            <Space direction="vertical" style={{ width: '100%' }}>
              <label htmlFor="cell-draft-value">新计划值</label>
              <InputNumber
                id="cell-draft-value"
                aria-label="新计划值"
                min={0}
                value={draftValue}
                onChange={(next) => setDraftValue(next)}
                style={{ width: '100%' }}
              />
              <Space>
                <Button onClick={() => setEditing(false)}>取消</Button>
                <Button
                  type="primary"
                  onClick={() => {
                    onDraftChange(draftValue)
                    setEditing(false)
                    onClose()
                  }}
                >
                  加入 Draft
                </Button>
              </Space>
            </Space>
          ) : (
            <Button onClick={() => setEditing(true)}>调整本轮计划</Button>
          )}
        </section>
      )}
      {objectRef && <Tag style={{ marginTop: 12 }}>{objectRef}</Tag>}
    </Drawer>
  )
}
