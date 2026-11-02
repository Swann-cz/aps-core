import { Alert, Button, Empty, List, Space } from 'antd'
import { useCore } from '../app/CoreContext'
import { findingText, type ScenarioSummary } from '../api/core'
export function NoPlanNotice({ scenario }: { scenario: ScenarioSummary }) {
  return <Alert type="error" showIcon message="没排出计划" description={<Findings findings={scenario.findings} />} />
}
export function PlanNotice() {
  const { scenario } = useCore()
  return <Space direction="vertical" style={{ width: '100%', marginBottom: 12 }}>
    {scenario?.state === 'STALE' && <Alert type="warning" showIcon message="条件已改，当前显示的是上次计划" />}
    {scenario?.plan_status && scenario.no_plan && <NoPlanNotice scenario={scenario} />}
  </Space>
}
export function Findings({ findings }: { findings: unknown[] }) {
  return <List size="small" locale={{ emptyText: '无说明' }} dataSource={findings} renderItem={item => <List.Item>{findingText(item)}</List.Item>} />
}
export function NoPlan() {
  const { scenario, busy, run } = useCore()
  return <Empty description="尚未运行"><Button type="primary" disabled={!scenario || busy} loading={run.isPending} onClick={() => run.mutate(scenario!.id)}>运行</Button></Empty>
}
