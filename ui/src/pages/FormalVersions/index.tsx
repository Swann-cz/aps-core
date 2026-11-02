import { useEffect } from 'react'
import { Button, Card, Table, Tag } from 'antd'
import { useNavigate } from 'react-router-dom'
import { useCore } from '../../app/CoreContext'
import { PageHeader } from '../../components/PageHeader'
import type { ScenarioSummary } from '../../api/core'
import { NoPlanNotice } from '../../components/CorePlanState'

export function FormalVersions() {
  const { scenarios, list, select } = useCore()
  const navigate = useNavigate()
  useEffect(() => { void list.refetch() }, [list.refetch])
  const open = (scenario: ScenarioSummary) => { select(scenario.id); navigate('/annual-overview') }
  const rows = scenarios.filter(s => s.formal).sort((a, b) => b.formal!.confirmed_at.localeCompare(a.formal!.confirmed_at))
  return <>
    <PageHeader title="正式版本" subtitle="已定稿方案，只读查看" />
    <Card><Table<ScenarioSummary> rowKey="id" loading={list.isFetching} dataSource={rows} pagination={false} scroll={{ x: 1200 }}
      onRow={row => ({ onClick: () => open(row), style: { cursor: 'pointer' } })} columns={[
        { title: '名称', dataIndex: 'name', render: (name, row) => <Button type="link" onClick={event => { event.stopPropagation(); open(row) }}>{name}</Button> },
        { title: '定稿时间', render: (_, row) => row.formal!.confirmed_at.replace('T', ' ') },
        { title: '备注', render: (_, row) => row.formal!.note || '—' },
        { title: '来源方案', render: (_, row) => scenarios.find(s => s.id === row.formal!.source_id)?.name ?? row.formal!.source_id },
        { title: '判定', dataIndex: 'verdict', render: (value, row) => row.no_plan ? <NoPlanNotice scenario={row} /> : <Tag color={value === 'ACCEPT' ? 'green' : value === 'REJECT' ? 'red' : undefined}>{value === 'ACCEPT' ? '接受' : value === 'REJECT' ? '拒绝' : '无判定'}</Tag> },
        ...['L1a', 'L1c', 'L2', 'L3a', 'L5'].map((level, index) => ({ title: ['全期缺口', '月度带缺口', '换型与清线', '周六使用量', '高于目标在制'][index], key: level, render: (_: unknown, row: ScenarioSummary) => row.objective?.[level] ?? '—' })),
      ]} /></Card>
  </>
}
