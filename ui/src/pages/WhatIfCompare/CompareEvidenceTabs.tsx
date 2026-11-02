import { Empty, Table, Tabs, Tag } from 'antd'
import type { ColumnsType } from 'antd/es/table'
import { displayValue } from '../../utils/format'
import type { ComparisonMetric, DiffEntry, IntentDiff } from '../../types/api'

const decisionColumns: ColumnsType<DiffEntry> = [
  { title: '指标', dataIndex: 'display_name' },
  { title: '左', dataIndex: 'left_value', render: (v) => displayValue(v) },
  { title: '右', dataIndex: 'right_value', render: (v) => displayValue(v) },
  { title: '变化', dataIndex: 'change_type', render: (v: string) => <Tag>{changeLabel(v)}</Tag> },
]

const derivedColumns: ColumnsType<DiffEntry> = [
  { title: '派生指标', dataIndex: 'display_name' },
  { title: '左', dataIndex: 'left_value', render: (v) => displayValue(v) },
  { title: '右', dataIndex: 'right_value', render: (v) => displayValue(v) },
  { title: '差异（右-左）', dataIndex: 'delta', render: (v) => displayValue(v) },
  { title: '影响类别', dataIndex: 'category', render: (v: string) => <Tag>{categoryLabel(v)}</Tag> },
]

const intentColumns: ColumnsType<IntentDiff> = [
  { title: '意图指标', dataIndex: 'metric', render: (v) => v || '—' },
  { title: '优先级', dataIndex: 'priority_tier', render: (v) => (v ? <Tag color="gold">P{v}</Tag> : '—') },
  { title: '左状态', dataIndex: 'left_status', render: (v) => <Tag>{intentStatusLabel(v)}</Tag> },
  { title: '右状态', dataIndex: 'right_status', render: (v) => <Tag>{intentStatusLabel(v)}</Tag> },
]

function changeLabel(value: string): string {
  return ({ ADDED: '新增', REMOVED: '移除', CHANGED: '已变化', SAME: '相同' } as Record<string, string>)[value] ?? '不同'
}

function categoryLabel(value: string): string {
  return ({ DERIVED: '派生影响', ORGANIZATIONAL_DELTA: '生产组织变化', DECISION: '计划决策' } as Record<string, string>)[value] ?? '其他影响'
}

function intentStatusLabel(value: unknown): string {
  const key = String(value || '')
  return ({ SATISFIED: '已满足', VIOLATED: '未满足', NOT_EVALUATED: '未评估' } as Record<string, string>)[key] ?? '未评估'
}

function DiffTable({ rows, columns }: { rows: DiffEntry[]; columns: ColumnsType<DiffEntry> }) {
  return rows.length === 0 ? (
    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未评估（后端未返回该维度差异）" />
  ) : (
    <Table size="small" bordered rowKey={(row) => `${row.object_ref}-${row.metric_id}`} columns={columns} dataSource={rows} pagination={false} />
  )
}

export function CompareEvidenceTabs({
  keyDifferences,
  decisionDiff,
  derivedDiff,
  intentDiff,
}: {
  keyDifferences: ComparisonMetric[]
  decisionDiff: DiffEntry[]
  derivedDiff: DiffEntry[]
  intentDiff: IntentDiff[]
}) {
  return (
    <Tabs
      size="small"
      items={[
        {
          key: 'key-differences',
          label: '关键差异',
          children: keyDifferences.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未评估" />
          ) : (
            <Table
              size="small"
              bordered
              rowKey="metric_id"
              dataSource={keyDifferences}
              pagination={false}
              columns={[
                { title: '指标', dataIndex: 'label' },
                { title: '左', dataIndex: 'left_value', render: (v) => displayValue(v) },
                { title: '右', dataIndex: 'right_value', render: (v) => displayValue(v) },
                { title: '评价', dataIndex: 'evaluation', render: (v: string) => <Tag>{changeLabel(v)}</Tag> },
              ]}
            />
          ),
        },
        {
          key: 'decision',
          label: '计划决策',
          children: <DiffTable rows={decisionDiff} columns={decisionColumns} />,
        },
        {
          key: 'derived',
          label: '派生影响',
          children: <DiffTable rows={derivedDiff} columns={derivedColumns} />,
        },
        {
          key: 'intent',
          label: '业务目标',
          children: intentDiff.length === 0 ? (
            <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未评估（后端未返回意图差异）" />
          ) : (
            <Table size="small" bordered rowKey="intent_id" columns={intentColumns} dataSource={intentDiff} pagination={false} />
          ),
        },
      ]}
    />
  )
}
