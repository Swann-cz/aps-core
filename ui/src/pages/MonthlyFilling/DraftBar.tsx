import { Button, Space, Tag } from 'antd'

export function DraftBar({
  count,
  summaries,
  onClear,
  onPreview,
  previewing,
  disabled,
}: {
  count: number
  summaries: string[]
  onClear: () => void
  onPreview: () => void
  previewing: boolean
  disabled: boolean
}) {
  return (
    <div className="draft-bar" data-testid="draft-bar">
      <Space wrap>
        <Tag color={count > 0 ? 'blue' : 'default'}>本地 Draft：{count} 项</Tag>
        {summaries.slice(0, 4).map((summary) => (
          <Tag key={summary}>{summary}</Tag>
        ))}
      </Space>
      <Space>
        <Button size="small" onClick={onClear} disabled={count === 0 || disabled}>
          清空 Draft
        </Button>
        <Button
          size="small"
          type="primary"
          loading={previewing}
          onClick={onPreview}
          disabled={count === 0 || disabled}
        >
          预览影响
        </Button>
      </Space>
    </div>
  )
}
