import { useEffect, useState } from 'react'
import { ScenarioPicker } from '../../components/ScenarioPicker'
import { Alert, App, Button, Card, Collapse, Grid, Input, Space, Spin, Steps, Table, Typography } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { conditionNames, core, findingText, modeName, quantity, type Condition, type ScenarioSummary } from '../../api/core'
import { useCore, viewRevision } from '../../app/CoreContext'
import { Findings } from '../../components/CorePlanState'
import { PageHeader } from '../../components/PageHeader'
import { FullImport } from '../NewPlan/FullImport'
import { SplitImport } from '../NewPlan'
import { NODE_NAMES } from '../PlanningConditions/ConditionDrawer'
import { SuggestCard, type SuggestAction } from '../PlanningConditions/SuggestCard'
import { wizardStep } from './state'

const stepNames = ['导入', '检查', '排产条件', '运行', '补缺口', '定稿']
function Conclusion({ scenario }: { scenario: ScenarioSummary }) {
  const navigate = useNavigate()
  const objective = scenario.objective
  const noPlan = scenario.no_plan || scenario.state === 'FAILED'
  const rejected = scenario.verdict === 'REJECT'
  const hasGap = !!objective && (objective.L1a > 0 || objective.L1c > 0)
  return <Card className="wizard-conclusion">
    <Typography.Title level={3} type={noPlan || rejected ? 'danger' : scenario.verdict === 'ACCEPT' ? (hasGap ? 'warning' : 'success') : undefined}>
      {noPlan ? '没有排出计划' : rejected ? `计划没通过校验，硬错误 ${quantity(scenario.hard_error_count)} 条` : scenario.verdict === 'ACCEPT' ? (hasGap ? '排出来了，但还有缺口' : '排出来了') : '计划尚无判定'}
    </Typography.Title>
    {noPlan ? <p>{scenario.run.error ?? (scenario.findings.length ? findingText(scenario.findings[0]) : '无说明')}</p> : rejected ? <Button type="link" onClick={() => navigate('/annual-overview#hard-errors')}>查看硬错误明细</Button> : objective && <Space wrap size={[24, 8]}>
      <span>全年缺口 {quantity(objective.L1a)} 台</span>
      <span>月度带缺口 {objective.L1c.toLocaleString('zh-CN')} 台</span>
      <span>换型与清线 {quantity(objective.L2)} 次</span>
      <span>周六 {quantity(objective.L3a)} 车间·日</span>
      <span>加班 {quantity(objective.L3b)} 车间·日</span>
      {scenario.solver && <span>用时 {Math.round(scenario.solver.seconds)} 秒</span>}
    </Space>}
  </Card>
}
function DetailLinks() {
  const navigate = useNavigate()
  return <Space wrap><Button type="link" onClick={() => navigate('/annual-overview')}>查看年度总览</Button><Button type="link" onClick={() => navigate('/monthly-filling')}>查看月度明细</Button></Space>
}
export function Wizard() {
  const { scenario, list } = useCore()
  if (list.isLoading) return <Spin />
  return <WizardScenario key={scenario?.id ?? 'new'} />
}
function WizardScenario() {
  const state = useCore()
  const scenario = state.scenario
  const navigate = useNavigate()
  const client = useQueryClient()
  const { message } = App.useApp()
  const screens = Grid.useBreakpoint()
  const [newImport, setNewImport] = useState(false)
  const [checked, setChecked] = useState(false)
  const [review, setReview] = useState<{ revision: string; step: number }>()
  const [note, setNote] = useState('')
  const [applied, setApplied] = useState(false)
  const [, tick] = useState(0)
  const running = scenario?.run.state === 'RUNNING' || scenario?.state === 'RUNNING'
  useEffect(() => {
    setApplied(false)
    if (!running) return
    setNewImport(false); setReview(undefined)
    const timer = window.setInterval(() => tick(value => value + 1), 1000)
    return () => window.clearInterval(timer)
  }, [scenario?.run.started_at, running])
  const conditionsKey = ['core', 'conditions', scenario?.id]
  const conditions = useQuery({ queryKey: conditionsKey, queryFn: () => core.conditions(scenario!.id), enabled: !!scenario })
  const suggestKey = ['core', 'suggest', scenario?.id, ...viewRevision(scenario)]
  const suggest = useQuery({ queryKey: suggestKey, queryFn: () => core.suggest(scenario!.id), enabled: !!scenario?.plan_status && !scenario.no_plan && !running })
  const suggestion = useMutation({
    mutationFn: (action: SuggestAction) => ({ candidates: core.suggestCandidates, apply: core.suggestApply, discard: core.suggestDiscard })[action](scenario!.id),
    onSuccess: async (view, action) => {
      client.setQueryData(suggestKey, view)
      setApplied(action === 'apply')
      await Promise.all([
        client.invalidateQueries({ queryKey: conditionsKey }),
        client.invalidateQueries({ queryKey: ['core', 'scenarios'] }),
        client.invalidateQueries({ queryKey: ['core', 'suggest', scenario!.id] }),
      ])
    },
    onError: (error: Error) => { void message.error(error.message) },
  })
  const finalize = useMutation({
    mutationFn: () => core.finalize(scenario!.id, note),
    onSuccess: summary => { state.update(summary); state.select(summary.id); void message.success('已定为正式版') },
    onError: (error: Error) => { void message.error(error.message) },
  })
  const current = newImport ? 0 : wizardStep(scenario, suggest.data)
  const revision = JSON.stringify([scenario?.id, ...viewRevision(scenario), scenario?.run.started_at, suggest.data?.stage])
  const step = current === 0 ? 0 : review?.revision === revision ? review.step : current
  const readOnly = Boolean(scenario?.formal)
  const disabled = state.busy || state.run.isPending || suggestion.isPending || finalize.isPending
  const startRun = () => { setReview(undefined); setNewImport(false); setApplied(false); state.run.mutate(scenario!.id) }
  const showConclusion = !!scenario && (step >= 4 || step === 3 && !running && (scenario.no_plan || scenario.state === 'FAILED'))
  return <div className="core-wizard">
    <PageHeader title="排产向导" subtitle="导入计划、确认条件、运行排产，最后定稿。" actions={<Button disabled={suggestion.isPending || finalize.isPending} onClick={() => { setNewImport(true); setReview(undefined); setChecked(false) }}>新建一份排产</Button>} />
    {!newImport && scenario && <Card size="small" className="wizard-current"><Space wrap size={12}><span>当前方案</span><ScenarioPicker width={460} /><Typography.Text type="secondary">换一份：在下拉框里选，或点右上角“新建一份排产”</Typography.Text></Space></Card>}
    <Card className="wizard-steps">
      <Steps direction={screens.lg ? 'horizontal' : 'vertical'} current={current} onChange={index => {
        if (running || current === 0 || index >= current || readOnly && index < 2) return
        setReview({ revision, step: index === 1 ? 0 : index })
      }} items={stepNames.map((title, index) => ({
        title,
        disabled: running || current === 0 || index >= current || readOnly && index < 2,
        ...(current === 0 && checked && index < 2 ? { status: 'finish' as const } : {}),
      }))} />
    </Card>
    {readOnly && !newImport && <Alert type="success" showIcon message="已定为正式版" description="正式版本只读，可以查看计划和条件。" />}
    {applied && step >= 4 && <Alert type="success" showIcon message="已采纳：只保留用到的授权，计划不变，判定已按新条件更新" />}
    {step === 0 && <Space direction="vertical" size={16} style={{ width: '100%' }}>
      <FullImport wizard onChecked={setChecked} onCreated={() => { setNewImport(false); setReview(undefined) }} />
      <Collapse items={[{ key: 'other', label: '其他导入方式', children: <SplitImport onCreated={() => { setNewImport(false); setReview(undefined) }} /> }]} />
    </Space>}
    {step === 2 && scenario && <Card title="第 3 步 · 排产条件">
      <Space direction="vertical" size={16} style={{ width: '100%' }}>
        {scenario.state === 'STALE' && <Alert type="warning" showIcon message="条件已改，需要重新运行" />}
        <p>确认带入的条件，需要调整时可前往排产条件页修改，再回到向导。</p>
        {conditions.isLoading ? <Spin /> : conditions.isError ? <Alert type="error" message={conditions.error.message} /> : conditions.data && <>
          <p>{conditions.data.conditions.length ? `已从导入文件带入 ${conditions.data.conditions.length} 条条件。` : '导入文件里没有条件。'}</p>
          <Table<Condition> rowKey="id" dataSource={conditions.data.conditions} pagination={false} scroll={{ x: 650 }} columns={[
            { title: '类型', render: (_, row) => conditionNames[row.type] },
            { title: '日期', render: (_, row) => row.date ?? row.pre_stop_date ?? `${row.start} 至 ${row.end}` },
            { title: '车间 / 节点', render: (_, row) => row.node ? NODE_NAMES[row.node] : row.workshop ? NODE_NAMES[row.workshop] : row.workshops?.map(ws => NODE_NAMES[ws]).join('、') ?? (row.type === 'PRE_STOP_TARGET' ? '涂装' : '全部车间') },
            { title: '数值', render: (_, row) => row.mode ? modeName(row.mode) : row.hours_max !== undefined ? `${row.hours_max} 小时` : row.target !== undefined ? `${quantity(row.target)} 台` : row.out !== undefined ? `${quantity(row.out)} 台` : '—' },
          ]} />
        </>}
        <Space wrap>
          {!readOnly && <Button type="primary" className="wizard-primary" disabled={disabled || !conditions.data} loading={state.run.isPending} onClick={startRun}>开始排产</Button>}
          <Button onClick={() => navigate('/planning-conditions')}>{readOnly ? '查看排产条件' : '去排产条件页修改'}</Button>
        </Space>
      </Space>
    </Card>}
    {showConclusion && <><Conclusion scenario={scenario!} /><DetailLinks /></>}
    {step === 3 && scenario && <Card title="第 4 步 · 运行">
      {running ? <Space direction="vertical" size={16}>
        <Typography.Title className="wizard-timer" level={2} aria-live="polite">已用 {Math.max(0, Math.floor((Date.now() - new Date(scenario.run.started_at!).getTime()) / 1000))} 秒</Typography.Title>
        <p>一般 1–3 分钟，期间可以离开本页</p>
        <Button type="primary" className="wizard-primary" disabled>正在排产</Button>
      </Space> : scenario.no_plan || scenario.state === 'FAILED' ? <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <Findings findings={scenario.findings} />
        {!readOnly && <Space wrap><Button type="primary" className="wizard-primary" onClick={() => navigate('/planning-conditions')}>回到排产条件</Button><Button disabled={disabled} onClick={startRun}>重新运行</Button></Space>}
      </Space> : suggest.isError ? <Alert type="error" showIcon message={suggest.error.message} /> : current > 3 ? <Space direction="vertical"><p>本次排产已结束。</p><Button type="primary" className="wizard-primary" onClick={() => setReview(undefined)}>查看排产结论</Button></Space> : <Spin tip="正在读取排产结论"><div style={{ minHeight: 60 }} /></Spin>}
    </Card>}
    {step === 4 && scenario && <>
      {suggest.isError ? <Alert type="error" showIcon message={suggest.error.message} /> : suggest.data && <SuggestCard view={suggest.data} readOnly={readOnly} disabled={disabled} pending={suggestion.isPending ? suggestion.variables : undefined} applied={false} onAction={action => suggestion.mutate(action)} />}
      {!readOnly && suggest.data?.stage === 'CANDIDATES_PENDING' && <Button type="primary" className="wizard-primary" disabled={disabled} onClick={startRun}>运行候选排产</Button>}
      {!readOnly && suggest.data?.stage === 'EXHAUSTED' && <Button onClick={() => setReview({ revision, step: 5 })}>仍然定为正式版</Button>}
    </>}
    {(step === 5 || step === 6) && scenario && <Card title={readOnly ? '定稿完成' : '第 6 步 · 定稿'}>
      {readOnly ? <Space direction="vertical"><p>已定为正式版：{scenario.name}</p><p>备注：{scenario.formal!.note || '无'}</p></Space> : <Space direction="vertical" size={16} style={{ width: '100%' }}>
        <p>确认排产结论，填写备注后保存为正式版本。</p>
        <Input.TextArea aria-label="定稿备注" placeholder="备注（可空）" value={note} onChange={event => setNote(event.target.value)} disabled={finalize.isPending} />
        {scenario.verdict !== 'ACCEPT' && <Alert type="error" showIcon message="计划通过校验后才能定稿" />}
        <Button type="primary" className="wizard-primary" disabled={disabled || scenario.state !== 'READY' || scenario.verdict !== 'ACCEPT'} loading={finalize.isPending} onClick={() => finalize.mutate()}>定为正式版</Button>
      </Space>}
    </Card>}
  </div>
}
