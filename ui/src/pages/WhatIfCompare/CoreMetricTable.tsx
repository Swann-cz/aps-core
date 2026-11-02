import { Table, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { displayValue } from '../../utils/format'
import type { ComparisonMetric } from '../../types/api'

const EVAL_LABELS: Record<ComparisonMetric['evaluation'], string> = {
  BETTER: '优势',
  WORSE: '代价',
  SAME: '相同',
  DIFFERENT: '不同',
  NOT_EVALUATED: '未评估',
}

function EvaluationCell({ metric }: { metric: ComparisonMetric }) {
  if (metric.evaluation === 'NOT_EVALUATED') {
    const basis = metric.basis || '当前接口未提供该指标'
    return <Tag color="default">未评估：{basis}</Tag>
  }
  return <Tag color={metric.evaluation === 'BETTER' ? 'green' : metric.evaluation === 'WORSE' ? 'red' : 'default'}>{EVAL_LABELS[metric.evaluation]}</Tag>
}

export function CoreMetricTable({ metrics }: { metrics: ComparisonMetric[] }) {
  const columns: ColumnsType<ComparisonMetric> = [
    { title: '指标', dataIndex: 'label', width: 200 },
    { title: '左版本', dataIndex: 'left_value', render: (v) => (v === null || v === undefined ? '—' : displayValue(v)) },
    { title: '右版本', dataIndex: 'right_value', render: (v) => (v === null || v === undefined ? '—' : displayValue(v)) },
    { title: '评价', key: 'evaluation', render: (_, m) => <EvaluationCell metric={m} /> },
  ]
  return (
    <Table
      size="small"
      bordered
      rowKey="metric_id"
      data-testid="compare-core-metrics"
      className="compare-core-metrics"
      columns={columns}
      dataSource={metrics}
      pagination={false}
    />
  )
}
