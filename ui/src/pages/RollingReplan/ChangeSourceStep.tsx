import { Card, Radio } from 'antd'
import type { ChangeSource } from './types'

const SOURCES: { value: ChangeSource; title: string; description: string }[] = [
  { value: 'actual', title: '实际产量更新', description: '以最新 ActualRevision 为事实更新' },
  { value: 'sales', title: '销售计划更新', description: '以新销售计划版本更新需求' },
  { value: 'conditions', title: '排产条件调整', description: '调整条件后重新排产' },
  { value: 'combined', title: '综合更新', description: '多个来源同时变化' },
]

export function ChangeSourceStep({
  source,
  onChange,
  onNext,
  baseConfirmedId,
  blocked,
}: {
  source: ChangeSource
  onChange: (source: ChangeSource) => void
  onNext: () => void
  baseConfirmedId: string | null
  blocked: boolean
}) {
  return (
    <Card size="small" title="第 1 步 · 变化来源">
      {baseConfirmedId && (
        <div className="muted" style={{ marginBottom: 10 }}>
          基准（Base Confirmed）：<code>{baseConfirmedId.slice(0, 8)}</code>（只读，发起新一轮时固定）
        </div>
      )}
      <Radio.Group value={source} onChange={(event) => onChange(event.target.value)} style={{ width: '100%' }}>
        <div className="change-source-grid">
          {SOURCES.map((item) => (
            <Radio.Button key={item.value} value={item.value} className="change-source-card">
              <strong>{item.title}</strong>
              <small>{item.description}</small>
            </Radio.Button>
          ))}
        </div>
      </Radio.Group>
      <button type="button" disabled={blocked} className="ant-btn ant-btn-primary" style={{ marginTop: 14 }} onClick={onNext}>
        下一步：更新输入
      </button>
    </Card>
  )
}
