import { Button, Descriptions, Drawer, List } from 'antd'
import { capText, conditionNames, modeName, phaseName, quantity, type AnnualDay, type AnnualView } from '../../api/core'
export function AnnualDateDrawer({ day, stops, caps, onClose, onOpenFilling }: { day: AnnualDay | undefined; stops: AnnualView['stop_list']; caps: AnnualView['caps']; onClose: () => void; onOpenFilling: () => void }) {
  return <Drawer title={(day?.date ?? '') + ' 日期详情'} open={!!day} onClose={onClose} width={480}>
    {day && <><Descriptions column={1} bordered size="small">
      <Descriptions.Item label="阶段">{phaseName(day.phase)}</Descriptions.Item>
      <Descriptions.Item label="生产模式">{modeName(day.mode_summary)}</Descriptions.Item>
      <Descriptions.Item label="完工（台）">{quantity(day.fok)}</Descriptions.Item>
      <Descriptions.Item label="当天条件">{day.conditions.map(c => c.id + '：' + conditionNames[c.type]).join('；') || '无'}</Descriptions.Item>
    </Descriptions><List header="所在停线窗口" locale={{ emptyText: '无停线窗口' }} dataSource={stops.filter(s => s.start <= day.date && s.end >= day.date)} renderItem={s => <List.Item>{s.start} 至 {s.end}（{s.length} 天）；停前日：{s.pre_stop_date ?? '无'}；目标：{s.target === null ? '无' : quantity(s.target) + ' 台'}；涂装{capText(caps.PS)}；来源：{s.source === 'DEFAULT' ? '默认' : s.source.replace('MANUAL:', '人工条件：')}</List.Item>} />
      <Button type="primary" onClick={onOpenFilling}>打开当月明细</Button></>}
  </Drawer>
}
