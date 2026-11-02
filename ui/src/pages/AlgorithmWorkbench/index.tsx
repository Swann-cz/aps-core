import { Descriptions, Drawer, List, Space, Tag } from 'antd'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { usePlanning } from '../../app/PlanningContext'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import type { AlgorithmProfile, AlgorithmSlot } from '../../types/api'

const SLOTS: { key: keyof AlgorithmProfile; label: string; description: string }[] = [
  { key: 'inventory_policy', label: '库存策略', description: '决定库存水平和补货策略' },
  { key: 'monthly_pp_allocation', label: '月度 PP 分配', description: '决定月度生产计划分配方式' },
  { key: 'working_mode_selection', label: '班制选择', description: '决定工作班制和加班策略' },
  { key: 'block_placement', label: '生产块放置', description: '决定生产块的放置规则' },
  { key: 'welding_sequence', label: '焊接顺序', description: '决定焊接工序的排序规则' },
  { key: 'candidate_selection', label: '候选方案选择', description: '决定候选方案的选择规则' },
]

function SlotOptions({ slot }: { slot: keyof AlgorithmProfile }) {
  const { data = [] } = useQuery({
    queryKey: ['algorithm-options', slot],
    queryFn: () => api.getAlgorithmOptions(slot),
    staleTime: 30_000,
  })
  return data.length <= 1 ? (
    <span className="muted">当前没有其他可选算法</span>
  ) : (
    <span className="muted">可选择 {data.length} 个算法</span>
  )
}

export function AlgorithmWorkbench() {
  const planning = usePlanning()
  const [detail, setDetail] = useState<{ slot: string; item: AlgorithmSlot } | null>(null)

  const profileQuery = useQuery({
    queryKey: ['algorithm-profile', planning.current_plan_version_id],
    queryFn: () => api.algorithmProfile(planning.current_plan_version_id as string),
    enabled: Boolean(planning.current_plan_version_id),
    staleTime: 30_000,
  })

  if (profileQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (profileQuery.error)
    return <PageState kind="system-error" error={profileQuery.error} onRetry={() => window.location.reload()} />
  if (!profileQuery.data) return <PageState kind="empty" title="当前没有可查看的算法配置（需先有排产结果）" />

  const profile = profileQuery.data
  return (
    <div>
      <PageHeader title="算法配置" subtitle="六槽当前生效算法（只读；无候选时不提供试算）" />
      <List
        bordered
        dataSource={SLOTS}
        renderItem={(slot) => {
          const current = profile[slot.key] as AlgorithmSlot
          return (
            <List.Item
              actions={[
                <a key="detail" onClick={() => setDetail({ slot: slot.key, item: current })}>
                  技术详情
                </a>,
              ]}
            >
              <List.Item.Meta
                title={
                  <Space wrap>
                    <span>{slot.label}</span>
                    <Tag>{current?.display_name || '当前生效算法'}</Tag>
                    <Tag>版本 {current?.version || '未提供'}</Tag>
                  </Space>
                }
                description={
                  <Space direction="vertical" size={2}>
                    <span className="muted">{slot.description}</span>
                    <SlotOptions slot={slot.key} />
                    <span className="muted">来源：后端当前配置</span>
                  </Space>
                }
              />
            </List.Item>
          )
        }}
      />
      <Drawer
        title={`${SLOTS.find((s) => s.key === detail?.slot)?.label || ''} · 技术详情`}
        open={Boolean(detail)}
        onClose={() => setDetail(null)}
        width={420}
      >
        {detail && (
          <Descriptions column={1} size="small" bordered>
            <Descriptions.Item label="算法 ID">{detail.item.algorithm_id}</Descriptions.Item>
            <Descriptions.Item label="版本">{detail.item.version}</Descriptions.Item>
            <Descriptions.Item label="显示名">{detail.item.display_name}</Descriptions.Item>
          </Descriptions>
        )}
      </Drawer>
    </div>
  )
}
