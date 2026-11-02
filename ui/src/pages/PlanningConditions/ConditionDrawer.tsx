import { Button, Checkbox, Drawer, Form, Input, InputNumber, Radio, Space } from 'antd'
import { useEffect, useState } from 'react'
import { capText, conditionNames, modeName, type Condition, type ConditionsView, type ConditionType } from '../../api/core'
const conditionDescriptions: Record<ConditionType, string> = {
  SATURDAY_AUTH: '允许本来不上班的日子开线（默认全线，可只选部分车间）',
  MODE_AUTH: '某些车间在一段时间内可以用加班班制（如 8+2、双班）',
  SHUTDOWN: '某些车间在一段时间内必须停',
  CAPACITY_LOSS: '检修等原因，某些车间每天最多只能开几小时',
  WIP_TARGET: '某段时间把某个节点的目标在制改成指定值',
  PRE_STOP_TARGET: '指定某次停线前一天涂装降到多少',
  FIXED_OUTPUT: '某车间某天必须产出指定台数',
}
// 抽屉里不用下拉框：车间、节点、班制选项平铺成勾选框 / 单选按钮，一眼可见、不依赖弹出层
export const NODE_NAMES: Record<string, string> = { BS1: '焊装1', BS2: '焊装2', WBS: '焊装缓冲', PS: '涂装', PBS: '涂装缓冲', AS_MAIN: '总装主线', AS_FIN: '总装完成线' }
const nodeOption = (value: string) => ({ value, label: NODE_NAMES[value] ? `${NODE_NAMES[value]}（${value}）` : value })

export function ConditionDrawer({ open, initialValue, options, disabled, onClose, onApply }: { open: boolean; initialValue?: Condition; options: ConditionsView['options']; disabled: boolean; onClose: () => void; onApply: (value: Condition) => void }) {
  const [form] = Form.useForm<Condition>()
  const node = Form.useWatch('node', form)
  const cap = node ? options.caps[node] : null
  const [type, setType] = useState<ConditionType>('SATURDAY_AUTH')
  const [choosingType, setChoosingType] = useState(!initialValue)
  const [single, setSingle] = useState(true)
  useEffect(() => {
    if (!open) return
    form.resetFields()
    setType(initialValue?.type ?? 'SATURDAY_AUTH')
    setChoosingType(!initialValue)
    setSingle(!!initialValue?.date || !initialValue)
    // 新增时编号自动生成（时间戳尾数），可以改
    form.setFieldsValue(initialValue ?? { type: 'SATURDAY_AUTH', id: `C-${Date.now().toString().slice(-6)}` })
  }, [open, initialValue, form])
  const required = [{ required: true, message: '请填写此项' }]
  const dateField = (name: 'date' | 'start' | 'end' | 'pre_stop_date', label: string) => <Form.Item name={name} label={label} rules={required}><Input type="date" min={options.horizon.start} max={options.horizon.end} /></Form.Item>
  return <Drawer title={initialValue ? '编辑排产条件' : '新增排产条件'} width={560} open={open} onClose={onClose}>
    {choosingType && <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 12 }}>
      {(Object.keys(conditionDescriptions) as ConditionType[]).map(value => <Button key={value} disabled={disabled} style={{ height: '100%', padding: 16, whiteSpace: 'normal', textAlign: 'left', justifyContent: 'flex-start' }} onClick={() => {
        setType(value)
        form.setFieldValue('type', value)
        setChoosingType(false)
      }}>
        <span><strong style={{ display: 'block', marginBottom: 8 }}>{conditionNames[value]}</strong><span>{conditionDescriptions[value]}</span></span>
      </Button>)}
    </div>}
    <Form form={form} style={{ display: choosingType ? 'none' : undefined }} layout="vertical" preserve={false} disabled={disabled} onFinish={values => {
      const condition = { ...values }
      if ((type === 'SATURDAY_AUTH' || type === 'SHUTDOWN') && !condition.workshops?.length) delete condition.workshops
      onApply(condition)
    }}>
      <Space style={{ marginBottom: 24 }}><strong>{conditionNames[type]}</strong>{!initialValue && <Button type="link" disabled={disabled} onClick={() => setChoosingType(true)}>换一种</Button>}</Space>
      <Form.Item name="type" hidden rules={required}><Input /></Form.Item>
      <Form.Item name="id" label="编号" rules={required}><Input /></Form.Item>
      {type === 'SATURDAY_AUTH' && <Form.Item label="日期方式"><Radio.Group value={single} onChange={e => setSingle(e.target.value)} options={[{ value: true, label: '单日' }, { value: false, label: '日期范围' }]} /></Form.Item>}
      {type === 'PRE_STOP_TARGET' ? dateField('pre_stop_date', '停前日期') : type === 'FIXED_OUTPUT' || (type === 'SATURDAY_AUTH' && single) ? dateField('date', '日期') : <>{dateField('start', '开始日期')}{dateField('end', '结束日期')}</>}
      {['SATURDAY_AUTH', 'MODE_AUTH', 'SHUTDOWN', 'CAPACITY_LOSS'].includes(type) && <Form.Item name="workshops" label={type === 'SATURDAY_AUTH' || type === 'SHUTDOWN' ? '车间（留空表示全部）' : '车间'} rules={type === 'MODE_AUTH' || type === 'CAPACITY_LOSS' ? required : []}><Checkbox.Group options={options.workshops.map(nodeOption)} /></Form.Item>}
      {type === 'FIXED_OUTPUT' && <Form.Item name="workshop" label="车间" rules={required}><Radio.Group options={options.workshops.map(nodeOption)} /></Form.Item>}
      {type === 'WIP_TARGET' && <Form.Item name="node" label="节点" rules={required}><Radio.Group options={options.nodes.map(value => ({ value, label: `${nodeOption(value).label} · ${capText(options.caps[value])}` }))} /></Form.Item>}
      {type === 'MODE_AUTH' && <Form.Item name="mode" label="加班模式" rules={required}><Radio.Group options={options.auth_modes.map(value => ({ value, label: modeName(value) }))} /></Form.Item>}
      {type === 'CAPACITY_LOSS' && <Form.Item name="hours_max" label="工时上限（小时）" rules={required}><InputNumber min={0} precision={0} /></Form.Item>}
      {(type === 'WIP_TARGET' || type === 'PRE_STOP_TARGET') && <Form.Item name="target" label="目标在制（台）" extra={type === 'WIP_TARGET' ? node ? cap === null ? '上限 = 目标（随人工目标调整）' : `不能超过上限 ${cap}` : '请选择节点查看上限' : capText(options.caps.PS)} rules={required}><InputNumber min={0} precision={0} /></Form.Item>}
      {type === 'FIXED_OUTPUT' && <Form.Item name="out" label="指定产量（台）" rules={required}><InputNumber min={0} precision={0} /></Form.Item>}
      <Form.Item name="reason" label="备注"><Input.TextArea rows={3} /></Form.Item>
      <Space><Button onClick={onClose}>取消</Button><Button type="primary" htmlType="submit">应用到条件表</Button></Space>
    </Form>
  </Drawer>
}
