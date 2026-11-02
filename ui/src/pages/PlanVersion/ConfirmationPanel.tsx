import { useState } from 'react'
import { Alert, Button, Collapse, Descriptions, Modal, Space, Tag, Typography } from 'antd'
import { StatusTag } from '../../components/StatusTag'
import { PlannerStateTag } from '../../components/PlannerStateTag'
import { shortId, formatDateTime } from '../../utils/format'
import type { PlanHistory } from '../../types/api'

export function ConfirmationPanel({
  current,
  gate,
  plannerState,
  confirming,
  onConfirm,
}: {
  current: PlanHistory | null
  gate: any
  plannerState: string | null
  confirming: boolean
  onConfirm: () => void
}) {
  const [modalOpen, setModalOpen] = useState(false)
  if (!current) return null
  const confirmed = current.status === 'CONFIRMED'
  return (
    <div className="confirmation-panel" data-testid="confirmation-panel">
      <Descriptions column={2} size="small" bordered>
        <Descriptions.Item label="当前候选" span={2}>
          <Space>
            <strong>{current.display_name || shortId(current.plan_version_id)}</strong>
            <StatusTag value={current.status} />
            <PlannerStateTag value={plannerState} />
          </Space>
        </Descriptions.Item>
        <Descriptions.Item label="创建时间">{formatDateTime(current.created_at)}</Descriptions.Item>
        <Descriptions.Item label="版本 ID"><code>{shortId(current.plan_version_id)}</code></Descriptions.Item>
        {current.base_confirmed_plan_version_id && (
          <Descriptions.Item label="Base（确认基准）" span={2}><code>{shortId(current.base_confirmed_plan_version_id)}</code></Descriptions.Item>
        )}
        {current.parent_plan_version_id && (
          <Descriptions.Item label="Parent" span={2}><code>{shortId(current.parent_plan_version_id)}</code></Descriptions.Item>
        )}
        <Descriptions.Item label="确认条件" span={2}>
          <Space wrap>
            <Tag>{gate?.hard_valid === true ? '硬约束检查通过' : '硬约束检查未通过'}</Tag>
            <Tag>阻断问题：{gate?.blocking_issue_count ?? 0}</Tag>
            <Tag color={gate?.can_confirm === true ? 'green' : 'orange'}>
              {gate?.can_confirm === true ? '可确认' : '暂不可确认'}
            </Tag>
          </Space>
        </Descriptions.Item>
      </Descriptions>
      {(gate?.blocking_reasons || []).length > 0 && (
        <Alert
          type="warning"
          showIcon
          style={{ marginTop: 10 }}
          message="确认被以下条件阻止"
          description={<ul style={{ margin: 0, paddingLeft: 18 }}>{(gate.blocking_reasons as string[]).map((reason) => <li key={reason}>{businessBlockingReason(reason)}</li>)}</ul>}
        />
      )}
      {(gate?.blocking_reasons || []).length > 0 && (
        <Collapse
          ghost
          size="small"
          items={[{
            key: 'confirmation-technical',
            label: '技术详情',
            children: (
              <Space direction="vertical" size={4}>
                {(gate.blocking_reasons as string[]).map((reason) => (
                  <Typography.Text code key={reason}>{reason}</Typography.Text>
                ))}
              </Space>
            ),
          }]}
        />
      )}
      <Space style={{ marginTop: 12 }}>
        {confirmed ? (
          <Button type="primary" onClick={() => (window.location.href = '/rolling-replan')}>
            基于此版本发起新一轮
          </Button>
        ) : (
          <Button
            type="primary"
            loading={confirming}
            disabled={gate?.can_confirm !== true}
            onClick={() => setModalOpen(true)}
          >
            确认此版本
          </Button>
        )}
      </Space>
      <Modal
        title="确认并锁定此版本"
        open={modalOpen}
        onCancel={() => setModalOpen(false)}
        footer={[
          <Button key="cancel" onClick={() => setModalOpen(false)}>取消</Button>,
          <Button
            key="confirm"
            type="primary"
            loading={confirming}
            onClick={() => {
              setModalOpen(false)
              onConfirm()
            }}
          >
            确认并锁定此版本
          </Button>,
        ]}
      >
        <p>
          确认后该 PlanVersion 内容不可变；历史与决策日志保留；后续更新需基于此版本发起新一轮（新 Session / 新 PlanVersion）。
        </p>
      </Modal>
    </div>
  )
}

function businessBlockingReason(reason: string): string {
  if (reason.startsWith('no complete hard-valid plan')) {
    return '当前计划尚未通过全部硬约束校验。'
  }
  const issue = reason.match(/^unresolved planning issue [A-Z_]+:\s*(.*)$/)
  if (issue?.[1]) {
    if (issue[1].includes('INVENTORY_')) return '库存安全校验未通过，请前往待处理问题查看影响月份。'
    const closure = issue[1].match(
      /^([A-Z]) 在 (\d{4}-\d{2}) 前无法闭合到 (\d{4}-\d{2}): required (\d+), future mutable capacity (\d+), current mutable capacity (\d+)$/,
    )
    if (closure) {
      return `车型 ${closure[1]} 在 ${closure[2]} 前无法闭合至 ${closure[3]}：累计需要 ${closure[4]}，后续可调整产能 ${closure[5]}，当月可调整产能 ${closure[6]}。`
    }
    return issue[1]
  }
  return '存在尚未处理的确认条件，请前往待处理问题查看。'
}
