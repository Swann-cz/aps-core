import { useEffect, useState } from 'react'
import { Alert, App, Button, Card, Empty, Popconfirm, Space, Spin, Steps, Table, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { capText, core, conditionNames, modeName, quantity, type Condition, type ConditionsView } from '../../api/core'
import { useCore, viewRevision } from '../../app/CoreContext'
import { PlanNotice } from '../../components/CorePlanState'
import { PageHeader } from '../../components/PageHeader'
import { ConditionDrawer, NODE_NAMES } from './ConditionDrawer'
import { SuggestCard, type SuggestAction } from './SuggestCard'
export function PlanningConditions() {
  const { scenario } = useCore()
  if (!scenario) return <Empty description="请选择方案" />
  return <ConditionsEditor key={scenario.id} />
}
function ConditionsEditor() {
  const { scenario, busy, update, run } = useCore()
  const navigate = useNavigate()
  const client = useQueryClient()
  const { message } = App.useApp()
  const [draft, setDraft] = useState<Condition[] | null>(null)
  const [editIndex, setEditIndex] = useState<number | null>(null)
  const [open, setOpen] = useState(false)
  const [applied, setApplied] = useState(false)
  useEffect(() => { setApplied(false) }, [scenario!.run.started_at])
  const queryKey = ['core', 'conditions', scenario!.id]
  const query = useQuery({ queryKey, queryFn: () => core.conditions(scenario!.id) })
  const suggestKey = ['core', 'suggest', scenario!.id, ...viewRevision(scenario)]
  const suggest = useQuery({ queryKey: suggestKey, queryFn: () => core.suggest(scenario!.id) })
  const suggestion = useMutation({
    mutationFn: (action: SuggestAction) => ({ candidates: core.suggestCandidates, apply: core.suggestApply, discard: core.suggestDiscard })[action](scenario!.id),
    onSuccess: async (view, action) => {
      client.setQueryData(suggestKey, view)
      setApplied(action === 'apply')
      await Promise.all([
        client.invalidateQueries({ queryKey }),
        client.invalidateQueries({ queryKey: ['core', 'scenarios'] }),
        client.invalidateQueries({ queryKey: ['core', 'suggest', scenario!.id] }),
      ])
    },
    onError: (error: Error) => { void message.error(error.message) },
  })
  const readOnly = Boolean(scenario!.formal)
  const rows = draft ?? query.data?.conditions ?? []
  const save = useMutation({ mutationFn: () => core.saveConditions(scenario!.id, rows), onSuccess: summary => {
    update(summary)
    client.setQueryData<ConditionsView>(queryKey, old => old && ({ ...old, scenario: summary, conditions: rows }))
    setDraft(null)
    void client.invalidateQueries({ queryKey: ['core', 'suggest', scenario!.id] })
    void message.success('已保存，点运行重算')
  }, onError: (error: Error) => { void message.error(error.message) } })
  const startRun = () => run.mutate(scenario!.id, { onSuccess: () => navigate('/annual-overview') })
  const stepDisabled = busy || save.isPending || run.isPending || suggestion.isPending || open
  if (query.isLoading) return <Spin />
  if (query.isError) return <Alert type="error" showIcon message={query.error.message} />
  if (!query.data) return null
  return <>
    <PageHeader title="排产条件" subtitle={query.data.options.horizon.start + ' 至 ' + query.data.options.horizon.end} actions={!readOnly && <Space><Button disabled={busy || save.isPending || suggestion.isPending} onClick={() => { setEditIndex(null); setOpen(true) }}>新增条件</Button><Button type="primary" disabled={busy || draft === null || suggestion.isPending} loading={save.isPending} onClick={() => save.mutate()}>保存</Button></Space>} />
    {scenario!.state === 'NO_PLAN' && !readOnly && <Card title="新建排产 · 第 3 步：排产条件">
      <Space direction="vertical" size="middle" style={{ width: '100%' }}>
        <Steps size="small" current={2} items={['导入', '检查', '排产条件', '运行', '补缺口', '定稿'].map(title => ({ title }))} />
        <div>{query.data.conditions.length ? `已从导入文件带入 ${query.data.conditions.length} 条条件。` : '导入文件里没有条件。'}需要周六上班、加班、计划停线、产能损失等，点‘新增条件’添加；不需要可以直接运行。</div>
        <Space wrap>
          <Button type="primary" disabled={stepDisabled} loading={save.isPending || run.isPending} onClick={() => {
            if (draft !== null) save.mutate(undefined, { onSuccess: startRun })
            else startRun()
          }}>{draft !== null ? '保存并运行' : '运行'}</Button>
          {draft !== null && <Popconfirm title="未保存的修改会丢弃" okText="继续运行" cancelText="取消" disabled={stepDisabled} onConfirm={() => { setDraft(null); startRun() }}>
            <Button disabled={stepDisabled}>跳过，直接运行</Button>
          </Popconfirm>}
        </Space>
      </Space>
    </Card>}
    {readOnly && <Alert type="info" showIcon message="正式版本只读" />}
    {draft !== null && <Alert type="info" showIcon message="条件表有未保存的修改，请保存后再运行。" />}
    <PlanNotice />
    {suggest.isLoading ? <Card title="缺口与建议"><Spin /></Card> : suggest.isError ? <Card title="缺口与建议"><Alert type="error" showIcon message={suggest.error.message} /></Card> : suggest.data && <SuggestCard view={suggest.data} readOnly={readOnly} disabled={busy || save.isPending || suggestion.isPending || draft !== null || open} pending={suggestion.isPending ? suggestion.variables : undefined} applied={applied} onAction={action => suggestion.mutate(action)} />}
    <Card><Table rowKey={(_, index) => String(index)} pagination={false} dataSource={rows} scroll={{ x: 900 }} columns={[
      { title: '编号', render: (_, r) => {
        const candidate = r.id.startsWith('CAND-')
        const usage = suggest.data?.stage === 'CANDIDATES_DONE' ? suggest.data.usage : null
        const used = usage && (r.type === 'SATURDAY_AUTH' ? usage.saturdays_used.includes(r.date!) : usage.overtime_used.some(item => item.id === r.id))
        return <Space wrap>{r.id}{candidate && <Tag color="blue">候选</Tag>}{candidate && usage && <Tag color={used ? 'green' : 'default'}>{used ? '用到' : '没用到'}</Tag>}</Space>
      } },
      { title: '类型', dataIndex: 'type', render: (v: Condition['type']) => conditionNames[v] },
      { title: '日期', render: (_, r) => r.date ?? r.pre_stop_date ?? r.start + ' 至 ' + r.end },
      { title: '车间 / 节点', render: (_, r) => r.node ? NODE_NAMES[r.node] ?? r.node : r.workshop ? NODE_NAMES[r.workshop] ?? r.workshop : r.workshops?.map(ws => NODE_NAMES[ws] ?? ws).join('、') ?? (r.type === 'PRE_STOP_TARGET' ? '涂装' : '全部车间') },
      { title: '数值', render: (_, r) => r.mode ? modeName(r.mode) : r.hours_max !== undefined ? quantity(r.hours_max) + ' 小时' : r.target !== undefined ? quantity(r.target) + ' 台；' + capText(query.data.options.caps[r.type === 'PRE_STOP_TARGET' ? 'PS' : r.node!]) : r.out !== undefined ? quantity(r.out) + ' 台' : '—' },
      { title: '备注', dataIndex: 'reason' },
      ...(!readOnly ? [{ title: '操作', render: (_: unknown, r: Condition, index: number) => <Space><Button size="small" disabled={busy || save.isPending || suggestion.isPending} onClick={() => { setEditIndex(index); setOpen(true) }}>编辑</Button><Popconfirm title={'删除条件 ' + r.id + '？'} okText="删除" cancelText="取消" onConfirm={() => setDraft(rows.filter((_, i) => i !== index))}><Button size="small" danger disabled={busy || save.isPending || suggestion.isPending}>删除</Button></Popconfirm></Space> }] : []),
    ]} /></Card>
    {!readOnly && <ConditionDrawer open={open} initialValue={editIndex === null ? undefined : rows[editIndex]} options={query.data.options} disabled={busy || save.isPending} onClose={() => setOpen(false)} onApply={value => { setDraft(editIndex === null ? [...rows, value] : rows.map((r, i) => i === editIndex ? value : r)); setOpen(false) }} />}
  </>
}
