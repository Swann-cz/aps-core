import { Button, Table } from 'antd'
import { phaseName, quantity, type AnnualMonth } from '../../api/core'
export function MonthlyFactsTable({ months, onOpenMonth }: { months: AnnualMonth[]; onOpenMonth: (month: string) => void }) {
  return <Table size="small" bordered rowKey="month" pagination={false} scroll={{ x: 2300 }} dataSource={months} columns={[
    { title: '月份', dataIndex: 'month', fixed: 'left', width: 115, render: (v: string) => <Button type="link" onClick={() => onOpenMonth(v)}>{v}</Button> },
    ...(['pr', 'fok', 'ws', 'cum_gap', 'fin_eom'] as const).map((key, i) => ({ title: ['需求（台）', '完工（台）', '交付（台）', '累计缺口（台）', '月末成品（台）'][i], dataIndex: key, render: quantity })),
    { title: '月度带缺口（台）', dataIndex: 'band_short', render: (v: number) => v.toFixed(1) },
    ...['BS1', 'BS2', 'WBS', 'PS', 'PBS', 'AS_MAIN', 'AS_FIN'].map(node => ({ title: node + ' 月末在制（台）', dataIndex: ['wip_eom', node], render: quantity })),
    ...['BS1', 'BS2'].map(node => ({ title: node + ' 生产天数', dataIndex: ['weld_days', node], render: quantity })),
    { title: '周六天数', dataIndex: 'saturday_days', render: quantity }, { title: '加班天数', dataIndex: 'overtime_days', render: quantity },
    { title: '阶段', dataIndex: 'phases', render: (v: string[]) => v.map(phaseName).join('、') || '正常' },
  ]} />
}
