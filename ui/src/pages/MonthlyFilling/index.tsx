import { Alert, Button, Card, Empty, Select, Space, Spin } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { core } from '../../api/core'
import { useCore, viewRevision } from '../../app/CoreContext'
import { NoPlan, PlanNotice } from '../../components/CorePlanState'
import { PageHeader } from '../../components/PageHeader'
import { CoreFillingBusinessView } from './CoreFillingBusinessView'

export function MonthlyFilling() {
  const { scenario } = useCore()
  const [params, setParams] = useSearchParams()
  const annual = useQuery({ queryKey: ['core', 'annual', scenario?.id, ...viewRevision(scenario)], queryFn: () => core.annual(scenario!.id), enabled: !!scenario?.plan_status })
  const months = annual.data?.months.map(m => m.month) ?? []
  const month = params.get('month') ?? months[0]
  const query = useQuery({ queryKey: ['core', 'monthly', scenario?.id, month, ...viewRevision(scenario)], queryFn: () => core.monthly(scenario!.id, month), enabled: !!scenario?.plan_status && !!month })
  if (!scenario) return <Empty description="请选择方案" />
  if (scenario.state === 'NO_PLAN') return <NoPlan />
  const index = months.indexOf(month)
  const changeMonth = (value: string) => setParams({ month: value })
  return <>
    <PageHeader title="月度明细" subtitle="逐日流量与在制 · 数量单位：台" />
    <PlanNotice />
    <Card className="filling-toolbar"><Space>
      <Button disabled={index <= 0} onClick={() => changeMonth(months[index - 1])}>上月</Button>
      <Select aria-label="月份" value={month} style={{ width: 150 }} options={months.map(m => ({ value: m, label: m }))} onChange={changeMonth} />
      <Button disabled={index < 0 || index >= months.length - 1} onClick={() => changeMonth(months[index + 1])}>下月</Button>
    </Space></Card>
    {(annual.isError || query.isError) && <Alert type="error" showIcon message={annual.error?.message ?? query.error?.message} />}
    {(annual.isLoading || query.isLoading) && <Spin />}
    {query.data && <Card className="filling-card"><CoreFillingBusinessView view={query.data} /></Card>}
    {!scenario.plan_status && <Empty description={scenario.state === 'RUNNING' ? '运行中，等待生成计划' : '暂无计划'} />}
  </>
}
