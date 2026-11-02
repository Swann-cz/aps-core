import { Button, Card, Space } from 'antd'

export function GenerationComplete({
  planVersionId,
  annualClosure,
  productionDays,
  issueCount,
  onOpenAnnual,
  onOpenIssues,
}: {
  planVersionId: string | null
  annualClosure?: number | null
  productionDays?: number | null
  issueCount: number
  onOpenAnnual: () => void
  onOpenIssues: () => void
}) {
  return (
    <Card size="small" title="排产完成">
      <div className="generation-complete">
        <strong>年度计划已生成</strong>
        <div className="muted">
          版本 <code>{planVersionId ? planVersionId.slice(0, 8) : '—'}</code>
          {annualClosure != null && <> · 年度闭合差 {annualClosure}</>}
          {productionDays != null && <> · 生产天数 {productionDays}</>}
          {issueCount > 0 && <> · 待决策问题 {issueCount}</>}
        </div>
        <Space style={{ marginTop: 12 }}>
          <Button type="primary" onClick={onOpenAnnual}>查看年度总览</Button>
          {issueCount > 0 && <Button onClick={onOpenIssues}>查看问题</Button>}
        </Space>
      </div>
    </Card>
  )
}
