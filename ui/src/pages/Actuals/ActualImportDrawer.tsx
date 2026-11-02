import { useState } from 'react'
import { Alert, Button, DatePicker, Drawer, Space, Upload, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import dayjs from 'dayjs'
import { api } from '../../api/planning'

export function ActualImportDrawer({
  open,
  onClose,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  onSaved: (revisionId: string) => void
}) {
  const queryClient = useQueryClient()
  const [effectiveDate, setEffectiveDate] = useState<string>(dayjs().format('YYYY-MM-DD'))
  const [savedId, setSavedId] = useState<string | null>(null)

  const saveMutation = useMutation({
    mutationFn: (file: File) =>
      api.importActualRevision(file, effectiveDate, 'Actual 导入抽屉'),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        const id = String(
          (result as any).payload?.actual_revision_id ?? (result as any).actual_revision_id ?? '',
        )
        message.success('ActualRevision 已保存（未触发自动重排）')
        setSavedId(id)
        queryClient.invalidateQueries({ queryKey: ['actual-revisions'] })
        onSaved(id)
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  return (
    <Drawer title="导入实际产量" open={open} onClose={onClose} width={520}>
      <Alert
        type="info"
        showIcon
        message="保存 ActualRevision"
        description="Actual 是事实：保存只记录修订，不会自动触发重排。需要重排时请手动发起新一轮。"
        style={{ marginBottom: 16 }}
      />
      <Space direction="vertical" style={{ width: '100%' }} size={12}>
        <DatePicker
          value={dayjs(effectiveDate)}
          onChange={(value) => setEffectiveDate(value ? value.format('YYYY-MM-DD') : effectiveDate)}
          style={{ width: '100%' }}
          placeholder="生效日期"
        />
        <Upload.Dragger
          accept=".xlsx,.xls"
          showUploadList={false}
          disabled={saveMutation.isPending}
          beforeUpload={(file) => {
            saveMutation.mutate(file)
            return false
          }}
        >
          <p className="ant-upload-drag-icon"><UploadOutlined /></p>
          <p className="ant-upload-text">点击或拖入 Actual Excel 文件</p>
          <p className="ant-upload-hint">保存为一条 ActualRevision（可追溯 supersedes 链）</p>
        </Upload.Dragger>
        {savedId && (
          <Alert
            type="success"
            showIcon
            message="已保存 ActualRevision"
            description={
              <Space direction="vertical">
                <span>
                  修订 <code>{savedId.slice(0, 8)}</code> 已落库；计划未自动变化。
                </span>
                <Button
                  onClick={() => {
                    onClose()
                    window.location.href = `/rolling-replan?source=actual&revision_id=${encodeURIComponent(savedId)}`
                  }}
                >
                  基于当前确认版本发起新一轮
                </Button>
              </Space>
            }
          />
        )}
      </Space>
    </Drawer>
  )
}
