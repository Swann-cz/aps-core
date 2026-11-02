import { Button, Space } from 'antd'

export function VersionEditorFooter({
  dirty,
  saving,
  onCancel,
  onSave,
  note,
}: {
  dirty: boolean
  saving: boolean
  onCancel: () => void
  onSave: () => void
  note?: string
}) {
  return (
    <div className="version-editor-footer">
      <span>{dirty ? '有未保存修改' : note || '没有修改'}</span>
      <Space>
        <Button onClick={onCancel}>取消</Button>
        <Button
          type="primary"
          disabled={!dirty}
          loading={saving}
          onClick={onSave}
        >
          保存新版本
        </Button>
      </Space>
    </div>
  )
}
