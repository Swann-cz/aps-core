import { Alert, Button, Card, Col, Row, Space, Table, Tag, Typography } from 'antd'
import { modeName, quantity, type SuggestView } from '../../api/core'
import { NODE_NAMES } from './ConditionDrawer'

export type SuggestAction = 'candidates' | 'apply' | 'discard'
export function SuggestCard({ view, readOnly, disabled, pending, applied, onAction }: {
  view: SuggestView; readOnly: boolean; disabled: boolean; pending?: SuggestAction; applied: boolean
  onAction: (action: SuggestAction) => void
}) {
  const { stage, candidates, usage, baseline, current } = view
  const action = (kind: SuggestAction, label: string, primary = false) => !readOnly && <Button type={primary ? 'primary' : 'default'} disabled={disabled} loading={pending === kind} onClick={() => onAction(kind)}>{label}</Button>
  return <Card title="缺口与建议">
    <Space direction="vertical" size="middle" style={{ width: '100%' }}>
      {applied && <Alert type="success" showIcon message="已采纳：只保留用到的授权，计划不变，判定已按新条件更新" />}
      {stage === 'NEED_RUN' && <Typography.Text>先运行一次，才能看缺口</Typography.Text>}
      {stage === 'NO_GAP' && <Typography.Text type="success">当前条件下没有欠产，不需要加周六或加班</Typography.Text>}
      {(stage === 'HAS_GAP' || stage === 'EXHAUSTED') && <>
        <Table size="small" pagination={false} rowKey={row => `${row.month}-${row.model}`} dataSource={view.gaps} scroll={{ x: 560 }} columns={[
          { title: '月份', dataIndex: 'month' }, { title: '车型', dataIndex: 'model' },
          { title: '月末累计缺口', dataIndex: 'cum_gap', render: value => `${quantity(value)} 台` },
          { title: '低于月度带下限', dataIndex: 'band_short', render: value => `${quantity(value)} 台` },
        ]} />
      </>}
      {stage === 'HAS_GAP' && <>
        {/* TODO(边界): §9.5 未提供历史采纳标志，重新进入页面时仅能从升级档位识别上一轮采纳。 */}
        {(applied || view.next_mode === 'SINGLE_8P3' || view.next_mode === 'DOUBLE_SHIFT') && <Typography.Text type="secondary">上一轮已采纳，这次升一档加班再试</Typography.Text>}
        {action('candidates', view.next_mode === null ? '生成候选授权（周六）' : `生成候选授权（周六 + ${modeName(view.next_mode)}加班）`, true)}
        <Typography.Text type="secondary">会把欠产月及其前一个月的可用周六、加班一次性加为候选，运行后生成器只挑最少的用</Typography.Text>
      </>}
      {stage === 'EXHAUSTED' && <Typography.Text type="warning">欠产月附近可用的周六和各档加班都已让生成器挑过，剩余缺口要人工处理（例如调整销售计划、停线安排，或手工加更早的授权）</Typography.Text>}
      {stage === 'CANDIDATES_PENDING' && <>
        <Typography.Text>已加 {candidates.saturdays.length} 个候选周六、{candidates.overtime.length} 段候选加班，请点顶栏‘运行’</Typography.Text>
        {action('discard', '撤销候选')}
      </>}
      {stage === 'CANDIDATES_DONE' && usage && <>
        {baseline && current && <Typography.Text strong>欠产 {quantity(baseline.L1a)} → {quantity(current.L1a)} 台，月度带下限缺口 {quantity(baseline.L1c)} → {quantity(current.L1c)} 台</Typography.Text>}
        <Row gutter={[24, 16]}>
          <Col xs={24} md={12}><Typography.Title level={5}>用到的周六</Typography.Title><Space wrap>{usage.saturdays_used.length ? usage.saturdays_used.map(date => <Tag key={date} color="blue">{date}</Tag>) : <Typography.Text type="secondary">无</Typography.Text>}</Space></Col>
          <Col xs={24} md={12}><Typography.Title level={5}>用到的加班</Typography.Title><Space direction="vertical">
            {usage.overtime_used.length ? usage.overtime_used.map(item => <div key={item.id}>
              <div>{item.days[0].date} 至 {item.days[item.days.length - 1].date} · {item.days.length} 天 · {modeName(item.mode)}</div>
              <Typography.Text type="secondary">{['BS1', 'BS2', 'PS', 'AS_MAIN', 'AS_FIN'].filter(ws => item.days.some(day => day.workshops.includes(ws))).map(ws => NODE_NAMES[ws]).join('、')}</Typography.Text>
            </div>) : <Typography.Text type="secondary">无</Typography.Text>}
          </Space></Col>
        </Row>
        <Typography.Text type="secondary">没用到：周六 {usage.saturdays_unused.length} 个、加班 {usage.overtime_unused_ids.length} 段</Typography.Text>
        {current && current.L1a > 0 && <Typography.Text type="warning">候选用满仍欠产 {quantity(current.L1a)} 台，需要更高的加班模式或更早的周六，请手工补条件</Typography.Text>}
        {!readOnly && <Space wrap>{action('apply', '采纳：删掉没用到的候选', true)}{action('discard', '全部撤销')}</Space>}
      </>}
    </Space>
  </Card>
}
