import { Button, Descriptions, Drawer, Space, Tag } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'

function draftLabel(objectRef: string): string {
  // Backend ref shape: workshop/BS2/2026-08-17/out (or field/<field>@<date>).
  const raw = objectRef.replace('field/', '')
  const workshop = (raw.match(/workshop\/([A-Z0-9]+)/i) || [])[1]?.toUpperCase()
    || (raw.match(/bs1|bs2|ps|as/i) || [''])[0]?.toUpperCase()
  const date = (raw.match(/\d{4}-\d{2}-\d{2}/) || [''])[0]
  const field = raw.includes('/out') || raw.includes('_out') ? 'OUT' : ''
  return `${workshop || 'node'} ${date ? `${Number(date.slice(5, 7))}/${Number(date.slice(8))}` : ''} ${field}`.trim()
}

export function DraftImpactDrawer({
  open,
  basePlanVersionId,
  whatIfPlanVersionId,
  month,
  draftItems,
  onClose,
  onCompare,
  onApply,
  applying,
}: {
  open: boolean
  basePlanVersionId: string
  whatIfPlanVersionId: string
  month: string
  draftItems: { object_ref: string }[]
  onClose: () => void
  onCompare: () => void
  onApply: () => void
  applying: boolean
}) {
  const healthQuery = useQuery({
    queryKey: ['plan-health', whatIfPlanVersionId],
    queryFn: () => api.planHealth(whatIfPlanVersionId),
    enabled: open,
  })
  const annualQuery = useQuery({
    queryKey: ['annual-calendar', whatIfPlanVersionId],
    queryFn: () => api.annualCalendar(whatIfPlanVersionId),
    enabled: open,
  })
  const compareQuery = useQuery({
    queryKey: ['plan-comparison', basePlanVersionId, whatIfPlanVersionId],
    queryFn: () => api.comparePlans(basePlanVersionId, whatIfPlanVersionId),
    enabled: open,
  })

  const hard = healthQuery.data?.hard_validation
  const gap = annualQuery.data ? Number(annualQuery.data.annual_closure_gap ?? 0) : null
  const baseGap = Number(
    (compareQuery.data?.core_metrics || []).find((m: any) => m.metric_id === 'annual_closure_gap')?.left_value ?? 0,
  )
  const verdict = compareQuery.data?.verdict_summary || ''

  return (
    <Drawer title="Draft 影响预览" open={open} onClose={onClose} width={520}>
      <Descriptions column={1} size="small" bordered>
        <Descriptions.Item label="Hard Validation">
          {healthQuery.isLoading ? '…' : hard ? <Tag color="green">{String(hard)}</Tag> : <Tag color="orange">后端未返回</Tag>}
        </Descriptions.Item>
        <Descriptions.Item label="年度闭合">
          {gap === null ? '…' : `${gap}（基准 ${baseGap}，Δ ${gap - baseGap}）`}
        </Descriptions.Item>
        <Descriptions.Item label="影响单元格">
          <Space wrap>
            {draftItems.map((item) => (
              <Tag key={item.object_ref}>{draftLabel(item.object_ref)}</Tag>
            ))}
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="月份">{month}</Descriptions.Item>
      </Descriptions>
      {verdict && <div className="muted" style={{ marginTop: 12 }}>{verdict}</div>}
      <Space style={{ marginTop: 16 }}>
        <Button onClick={onCompare}>查看完整版本比对</Button>
        <Button type="primary" loading={applying} onClick={onApply}>
          应用并重新排产
        </Button>
      </Space>
    </Drawer>
  )
}
