import { useState } from 'react'
import { Button, Card, message, Space, Tag } from 'antd'
import { DeleteOutlined, EditOutlined, PlusOutlined } from '@ant-design/icons'
import { api } from '../../api/planning'
import { conditionActionLabel } from '../../utils/conditions'
import {
  ConditionDrawer,
  type ConditionComposerValue,
} from '../PlanningConditions/ConditionDrawer'
import type { ConditionDraft, StartPlanningDraft } from './types'

function draftSummary(item: ConditionDraft): string {
  const workshops = Array.isArray(item.params.workshop_ids)
    ? item.params.workshop_ids.join('/')
    : '全厂'
  const start = String(item.params.start_date ?? '')
  const end = String(item.params.end_date ?? '')
  return [workshops || '全厂', start && end ? `${start} ~ ${end}` : ''].filter(Boolean).join(' · ')
}

export function PlanningConditionsStep({
  draft,
  onChange,
  onNext,
  onBack,
}: {
  draft: StartPlanningDraft
  onChange: (draft: StartPlanningDraft) => void
  onNext: () => void
  onBack: () => void
}) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [editingDraftId, setEditingDraftId] = useState<string | null>(null)
  const editing = draft.conditionChanges.find((item) => item.draftId === editingDraftId) ?? null

  const closeDrawer = () => {
    setDrawerOpen(false)
    setEditingDraftId(null)
  }

  const addOrUpdate = async (value: ConditionComposerValue) => {
    try {
      const built = await api.buildCondition({
        action_type: value.actionType,
        params: value.params,
      })
      if (!built.planning_conditions?.length) {
        throw new Error('后端没有返回可执行排产条件')
      }
      const nextDraft: ConditionDraft = {
        draftId: editingDraftId ?? `condition-${Date.now()}`,
        actionType: value.actionType,
        params: value.params,
        actionPayload: built.payload,
        planningConditions: built.planning_conditions,
      }
      const next = editingDraftId
        ? draft.conditionChanges.map((item) => item.draftId === editingDraftId ? nextDraft : item)
        : [...draft.conditionChanges, nextDraft]
      onChange({ ...draft, conditionChanges: next })
      message.success(editingDraftId ? '排产条件已更新' : '排产条件已加入本轮')
      closeDrawer()
    } catch (error: any) {
      message.error(`条件编译失败: ${error?.message || String(error)}`)
    }
  }

  return (
    <Card
      size="small"
      title="第 2 步 · 排产条件"
      extra={
        <Button
          type="primary"
          icon={<PlusOutlined />}
          onClick={() => {
            setEditingDraftId(null)
            setDrawerOpen(true)
          }}
        >
          添加排产条件
        </Button>
      }
    >
      <div className="condition-groups">
        <section>
          <h4>从 Base 继承</h4>
          <div className="muted">
            {draft.baseConfirmedPlanVersionId
              ? `由后端继承确认版本 ${draft.baseConfirmedPlanVersionId.slice(0, 8)}`
              : '无'}
          </div>
        </section>
        <section>
          <h4>本轮新增</h4>
          <div style={{ marginBottom: 8 }}>本轮条件 {draft.conditionChanges.length} 条</div>
          {draft.conditionChanges.length === 0 ? (
            <div className="muted">无</div>
          ) : (
            <ul className="condition-group-list">
              {draft.conditionChanges.map((item) => (
                <li key={item.draftId}>
                  <Tag color="blue">{conditionActionLabel(item.actionType)}</Tag>
                  <span className="muted">{draftSummary(item)}</span>
                  <Space size={4}>
                    <Button
                      size="small"
                      icon={<EditOutlined />}
                      onClick={() => {
                        setEditingDraftId(item.draftId)
                        setDrawerOpen(true)
                      }}
                    >
                      调整本轮
                    </Button>
                    <Button
                      size="small"
                      danger
                      icon={<DeleteOutlined />}
                      onClick={() => onChange({
                        ...draft,
                        conditionChanges: draft.conditionChanges.filter((current) => current.draftId !== item.draftId),
                      })}
                    >
                      删除
                    </Button>
                  </Space>
                </li>
              ))}
            </ul>
          )}
        </section>
        <section>
          <h4>基础设置引用</h4>
          <div className="muted">激活的工厂模型、日历、WIP 目标与全年清线策略由后端统一构建；清线策略不会自行创建停线，需同时提供明确的停线条件。</div>
        </section>
      </div>

      <Space style={{ marginTop: 16 }}>
        <Button onClick={onBack}>上一步：销售计划</Button>
        <Button type="primary" onClick={onNext}>
          下一步：检查生成
        </Button>
      </Space>

      <ConditionDrawer
        open={drawerOpen}
        planningYear={draft.planningYear}
        initialValue={editing ? { actionType: editing.actionType, params: editing.params } : null}
        onClose={closeDrawer}
        onApply={addOrUpdate}
        applyLabel="加入本轮"
      />
    </Card>
  )
}
