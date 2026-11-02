import { useState } from 'react'
import { Alert, Button, Drawer, Input, Space, Steps, Upload, message } from 'antd'
import { UploadOutlined } from '@ant-design/icons'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from '../../api/planning'

type ImportStage = 'select' | 'uploading' | 'review' | 'complete'

export function SalesImportDrawer({
  open,
  onClose,
  onSaved,
}: {
  open: boolean
  onClose: () => void
  onSaved: (versionId: string) => void
}) {
  const queryClient = useQueryClient()
  const [stage, setStage] = useState<ImportStage>('select')
  const [result, setResult] = useState<any | null>(null)
  const [displayName, setDisplayName] = useState('')

  const importMutation = useMutation({
    mutationFn: ({ file, name }: { file: File; name: string }) => api.importSalesPlan(file, name),
    onSuccess: (data) => {
      if (data.outcome === 'CREATED') {
        setResult(data)
        setStage('review')
      } else {
        message.error(`导入失败：${data.message || data.outcome}（${data.outcome}）`)
        setStage('select')
      }
    },
    onError: (error) => {
      message.error(`导入失败：${error instanceof Error ? error.message : '未知错误'}`)
      setStage('select')
    },
  })

  const activateMutation = useMutation({
    mutationFn: (versionId: string) => api.activateSalesPlanVersion(versionId),
    onSuccess: (data) => {
      if (data.outcome === 'ACTIVATED') {
        message.success('已保存并使用新销售计划')
        queryClient.invalidateQueries({ queryKey: ['sales-plan-versions'] })
        queryClient.invalidateQueries({ queryKey: ['v6', 'pr'] })
        queryClient.invalidateQueries({ queryKey: ['v6', 'ws'] })
        setStage('complete')
        onSaved(String(result?.payload?.sales_plan_version_id ?? result?.sales_plan_version_id ?? ''))
      } else {
        message.error(`激活失败: ${data.outcome}`)
      }
    },
    onError: () => message.error('激活失败'),
  })

  const versionId = String(result?.payload?.sales_plan_version_id ?? result?.sales_plan_version_id ?? '')

  const reset = () => {
    setStage('select')
    setResult(null)
    setDisplayName('')
  }

  return (
    <Drawer
      title="导入新销售计划"
      open={open}
      onClose={() => {
        reset()
        onClose()
      }}
      width={520}
    >
      <Steps
        size="small"
        current={stage === 'select' ? 0 : stage === 'uploading' ? 0 : stage === 'review' ? 1 : 2}
        items={[{ title: '选择文件' }, { title: '校验' }, { title: '完成' }]}
        style={{ marginBottom: 16 }}
      />
      {stage === 'select' && (
        <>
          <Input
            aria-label="Sales 短名称"
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="输入销售计划短名称"
            style={{ marginBottom: 12 }}
          />
          <Upload.Dragger
            accept=".xlsx,.xls"
            showUploadList={false}
            beforeUpload={(file) => {
              const name = displayName.trim()
              if (!name) {
                message.error('请先输入非空 Sales 短名称')
                return false
              }
              setStage('uploading')
              importMutation.mutate({ file, name })
              return false
            }}
          >
            <p className="ant-upload-drag-icon"><UploadOutlined /></p>
            <p className="ant-upload-text">点击或拖入 Excel 销售计划文件</p>
            <p className="ant-upload-hint">导入创建新版本；激活是独立动作</p>
          </Upload.Dragger>
        </>
      )}
      {stage === 'uploading' && <Alert type="info" showIcon message="正在上传并校验…" />}
      {stage === 'review' && (
        <div>
          <Alert
            type="success"
            showIcon
            message="校验通过，已创建新版本"
            description={
              <span>
                销售计划「{displayName.trim()}」待激活为当前生效计划。
              </span>
            }
          />
          <Space style={{ marginTop: 16 }}>
            <Button onClick={reset}>重新导入</Button>
            <Button
              type="primary"
              loading={activateMutation.isPending}
              onClick={() => activateMutation.mutate(versionId)}
            >
              保存并使用
            </Button>
          </Space>
        </div>
      )}
      {stage === 'complete' && (
        <Alert type="success" showIcon message="新销售计划已生效" />
      )}
    </Drawer>
  )
}
