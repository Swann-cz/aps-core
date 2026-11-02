import { Alert, Card, Col, Collapse, Empty, Row, Spin, Table, Tag } from 'antd'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useLocation, useNavigate } from 'react-router-dom'
import { core, quantity } from '../../api/core'
import { useCore, viewRevision } from '../../app/CoreContext'
import { Findings, NoPlan, PlanNotice } from '../../components/CorePlanState'
import { PageHeader } from '../../components/PageHeader'
import { BarMetricChart, LineMetricChart } from '../../components/MetricChart'
import { AnnualCalendarGrid } from './AnnualCalendarGrid'
import { AnnualSummaryRail } from './AnnualSummaryRail'
import { AnnualDateDrawer } from './AnnualDateDrawer'
import { MonthlyFactsTable } from './MonthlyFactsTable'
const solverName = (name: string) => ({ segment: '段级解法', legacy: '旧解法', best: '两种解法取优' } as Record<string, string>)[name] ?? name
export function AnnualOverview() {
  const { scenario } = useCore()
  const navigate = useNavigate()
  const location = useLocation()
  const [focus, setFocus] = useState<string>()
  const query = useQuery({ queryKey: ['core', 'annual', scenario?.id, ...viewRevision(scenario)], queryFn: () => core.annual(scenario!.id), enabled: !!scenario?.plan_status })
  const options = useQuery({ queryKey: ['core', 'options', scenario?.id], queryFn: () => core.conditions(scenario!.id), enabled: !!scenario })
  if (!scenario) return <Empty description="请选择方案" />
  if (scenario.state === 'NO_PLAN') return <NoPlan />
  if (query.isError || options.isError) return <Alert type="error" showIcon message={query.error?.message ?? options.error?.message} />
  if (query.isLoading || options.isLoading) return <Spin />
  if (!query.data) return <Empty description={scenario.state === 'RUNNING' ? '运行中，等待生成计划' : '暂无计划'} />
  const data = query.data
  const openMonth = (month: string) => navigate('/monthly-filling?month=' + month)
  return <div className="annual-overview">
    <PageHeader title="年度总览" subtitle={data.horizon.start + ' 至 ' + data.horizon.end} />
    <PlanNotice />
    {!data.scenario.no_plan && <Card title="判定与目标" size="small">
      <Tag color={data.scenario.verdict === 'ACCEPT' ? 'green' : data.scenario.verdict === 'REJECT' ? 'red' : undefined}>{data.scenario.verdict === 'ACCEPT' ? '接受' : data.scenario.verdict === 'REJECT' ? '拒绝' : '无判定'}</Tag>
      <span>硬错误 {quantity(data.scenario.hard_error_count)} 条</span>
      {data.scenario.solver && <span style={{ marginLeft: 16 }}>本次使用：{solverName(data.scenario.solver.name)}，用时 {Math.round(data.scenario.solver.seconds)} 秒</span>}
      <Table size="small" pagination={false} rowKey="level" dataSource={['L1a', 'L1b', 'L1c', 'L2', 'L3a', 'L3b', 'L4', 'L5'].map((level, i) => ({ level, label: ['全期需求缺口（台）', '欠交（台·天）', '月度带缺口（台）', '换型与清线次数', '周六使用量（车间·日）', '加班使用量（车间·日）', '缓冲越带天数', '高于目标在制（台·天）'][i], value: data.scenario.objective?.[level] }))} columns={[{ title: '目标', render: (_, row) => <>{row.label} <small style={{ color: '#8b99b0' }}>{row.level}</small></> }, { title: '数值', render: (_, r) => r.value === undefined ? '无判定' : r.level === 'L1c' ? r.value.toFixed(1) : quantity(r.value) }]} />
      <div id="hard-errors"><Collapse defaultActiveKey={location.hash === '#hard-errors' ? ['errors'] : []} items={[{ key: 'errors', label: '硬错误明细（最多前 50 条）', children: <Table size="small" pagination={false} rowKey={(_, i) => String(i)} dataSource={data.hard_errors.slice(0, 50)} columns={[{ title: '规则', dataIndex: 'rule' }, { title: '日期', dataIndex: 'date' }, { title: '节点', dataIndex: 'node' }, { title: '车型', dataIndex: 'model' }, { title: '说明', dataIndex: 'detail' }]} /> }, { key: 'findings', label: '计划说明', children: <Findings findings={data.findings} /> }]} /></div>
    </Card>}
    <Row gutter={[16, 16]} className="annual-lower"><Col xs={24} xl={19}><Card title="年度日历" extra={<><Tag>停</Tag><Tag color="green">默认模式</Tag><Tag color="purple">加班模式</Tag><span>加 = 非工作日加班生产</span></>}>
      {options.data && <AnnualCalendarGrid days={data.days} authModes={options.data.options.auth_modes} onSelectDate={setFocus} />}
    </Card></Col><Col xs={24} xl={5}><AnnualSummaryRail totals={data.totals} /></Col></Row>
    <Row gutter={[16, 16]} className="annual-lower"><Col xs={24} lg={12}><Card title="月度需求 / 完工 / 交付（台）"><LineMetricChart months={data.months} series={[{ key: 'pr', label: '需求 PR', color: '#1d5fb8' }, { key: 'fok', label: '完工 FOK', color: '#1a8f5c' }, { key: 'ws', label: '交付 WS', color: '#d98e14' }]} /></Card></Col><Col xs={24} lg={12}><Card title="月末成品库存（台）"><BarMetricChart months={data.months} field="fin_eom" color="#1d5fb8" title="月末成品库存" /></Card></Col></Row>
    <Card title="月度事实" className="annual-lower"><MonthlyFactsTable months={data.months} onOpenMonth={openMonth} /></Card>
    <Card title="车型年度需求 / 完工 / 缺口（台）" className="annual-lower"><Table rowKey="model" pagination={false} dataSource={data.models} columns={[{ title: '车型', dataIndex: 'model' }, ...(['annual_pr', 'annual_fok', 'annual_gap'] as const).map((key, i) => ({ title: ['年度需求', '年度完工', '年度缺口'][i], dataIndex: key, render: quantity }))]} expandable={{ expandedRowRender: model => <Table size="small" rowKey="month" pagination={false} dataSource={Object.entries(model.months).map(([month, values]) => ({ month, ...values }))} columns={[{ title: '月份', dataIndex: 'month' }, ...(['pr', 'fok', 'cum_gap'] as const).map((key, i) => ({ title: ['需求', '完工', '累计缺口'][i], dataIndex: key, render: quantity })), { title: '月度带缺口', dataIndex: 'band_short', render: (v: number) => v.toFixed(1) }]} /> }} /></Card>
    <AnnualDateDrawer day={data.days.find(d => d.date === focus)} stops={data.stop_list} caps={data.caps} onClose={() => setFocus(undefined)} onOpenFilling={() => openMonth(focus!.slice(0, 7))} />
  </div>
}
