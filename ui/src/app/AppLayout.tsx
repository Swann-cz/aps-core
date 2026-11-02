import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons'
import { Alert, App, Button, Input, Layout, Menu, Modal, Space, Tag, Typography } from 'antd'
import { useEffect, useState, type ReactNode } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { core, planStatusName, type ScenarioSummary } from '../api/core'
import { useCore } from './CoreContext'
import { primaryNav } from './navigation'
import { ScenarioPicker } from '../components/ScenarioPicker'
function statusText(s: ScenarioSummary) {
  switch (s.state) {
    case 'RUNNING': return `运行中（已用 ${Math.floor((Date.now() - new Date(s.run.started_at!).getTime()) / 1000)} 秒）`
    case 'FAILED': return `运行失败：${s.run.error}`
    case 'NO_PLAN': return '尚未运行'
    case 'STALE': return '条件已改，计划未重算'
    case 'READY': return `${s.verdict === 'ACCEPT' ? '接受' : s.verdict === 'REJECT' ? '拒绝' : '无判定'} · ${s.plan_status ? planStatusName(s.plan_status) : '无计划'}`
  }
}
export function AppLayout({ children }: { children: ReactNode }) {
  const navigate = useNavigate()
  const location = useLocation()
  const state = useCore()
  const { message } = App.useApp()
  const [collapsed, setCollapsed] = useState(false)
  const [copyOpen, setCopyOpen] = useState(false)
  const [finalizeId, setFinalizeId] = useState<string | null>(null)
  const [note, setNote] = useState('')
  const [name, setName] = useState('')
  const [, setTick] = useState(0)
  useEffect(() => {
    if (state.scenario?.state !== 'RUNNING') return
    const timer = window.setInterval(() => setTick(tick => tick + 1), 1000)
    return () => window.clearInterval(timer)
  }, [state.scenario?.state])
  const copy = useMutation({ mutationFn: () => core.copy(state.scenario!.id, name.trim()), onSuccess: summary => { state.update(summary); state.select(summary.id); setCopyOpen(false); setName('') }, onError: (error: Error) => { void message.error(error.message) } })
  const finalize = useMutation({ mutationFn: () => core.finalize(finalizeId!, note), onSuccess: summary => {
    state.update(summary); state.select(summary.id); setFinalizeId(null); setNote('')
    void message.success('已定为正式版')
  }, onError: (error: Error) => { void message.error(error.message) } })
  return <Layout className="app-shell">
    <Layout.Sider className="app-sider" width={204} collapsedWidth={64} collapsed={collapsed} breakpoint="lg" onBreakpoint={setCollapsed}>
      <div className="brand-mark"><span className="brand-logo">⚙</span>{!collapsed && <span><strong>APS 排产工作台</strong><small>核心排产</small></span>}</div>
      <Menu mode="inline" selectedKeys={[location.pathname]} items={primaryNav} onClick={({ key }) => navigate(key)} />
      <div className="sider-collapse"><Button type="text" aria-label={collapsed ? '展开导航' : '收起导航'} icon={collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />} onClick={() => setCollapsed(!collapsed)}>{!collapsed && '收起'}</Button></div>
    </Layout.Sider>
    <Layout><Layout.Header className="top-header core-header"><Space wrap>
      <span>方案</span><ScenarioPicker />
      {state.scenario && (state.scenario.state === 'RUNNING' || state.scenario.state === 'FAILED') && <Tag color={state.scenario.state === 'FAILED' ? 'red' : 'processing'}>{statusText(state.scenario)}</Tag>}
      {state.scenario?.run.state === 'IDLE' && state.scenario.run.kept_previous && <Typography.Text type="secondary">新结果没有更好，沿用上一版计划（已按新条件重新判定）</Typography.Text>}
      {!state.scenario?.formal && <Button type="primary" disabled={!state.scenario || state.busy} loading={state.run.isPending} onClick={() => state.run.mutate(state.scenario!.id)}>运行</Button>}
      {state.scenario?.formal && <Tag>正式版本只读</Tag>}
      {state.scenario?.state === 'READY' && state.scenario.verdict === 'ACCEPT' && !state.scenario.formal && <Button onClick={() => { setFinalizeId(state.scenario!.id); setNote('') }}>定为正式版</Button>}
      <Button disabled={!state.scenario} onClick={() => setCopyOpen(true)}>另存为新方案</Button>
    </Space></Layout.Header>
      <Layout.Content className="app-content">{state.list.isError && <Alert type="error" showIcon message={state.list.error.message} />}{children}</Layout.Content>
    </Layout>
    <Modal title="定为正式版" open={finalizeId !== null} okText="确认定稿" cancelText="取消" confirmLoading={finalize.isPending} onOk={() => finalize.mutate()} onCancel={() => setFinalizeId(null)} cancelButtonProps={{ disabled: finalize.isPending }} closable={!finalize.isPending} maskClosable={!finalize.isPending}>
      <p>{state.scenarios.find(s => s.id === finalizeId)?.name}</p>
      <Input.TextArea aria-label="定稿备注" placeholder="备注（可空）" value={note} onChange={event => setNote(event.target.value)} disabled={finalize.isPending} />
    </Modal>
    <Modal title="另存为新方案" open={copyOpen} okText="创建方案" cancelText="取消" confirmLoading={copy.isPending} okButtonProps={{ disabled: !name.trim() }} onOk={() => copy.mutate()} onCancel={() => setCopyOpen(false)}><Input aria-label="新方案名称" placeholder="请输入新方案名称" value={name} onChange={event => setName(event.target.value)} /></Modal>
  </Layout>
}
