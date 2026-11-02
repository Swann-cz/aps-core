import { useEffect, useMemo } from 'react'
import {
  Alert,
  Button,
  Card,
  Divider,
  Drawer,
  Form,
  Input,
  InputNumber,
  Select,
  Space,
  Tag,
  Typography,
} from 'antd'
import { MinusCircleOutlined, PlusOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { v6Api } from '../api/v6'
import type {
  V6ConditionComposerValue,
  V6ConditionOption,
} from '../types/v6'

type FactoryScope = {
  workshops: string[]
  buffers: string[]
  wipNodes: { value: string; label: string }[]
  typeclasses: string[]
  workingModes: string[]
}

const drawerPopupContainer = (trigger: HTMLElement) =>
  trigger.parentElement || document.body

const CATEGORY_LABELS: Record<string, string> = {
  CALENDAR: '日历',
  CAPACITY: '产能',
  WORKING_MODE: '工作模式',
  RESTART: '复线',
  WIP: 'WIP',
  OUTPUT: '产量',
  PREFERENCE: '偏好',
}

const SEMANTIC_COLORS: Record<string, string> = {
  HARD_CONSTRAINT: 'red',
  HARD_DECISION: 'red',
  CAPABILITY: 'purple',
  POLICY: 'gold',
  INTENT: 'blue',
}

const SUPPORTED_EDITORS = new Set([
  'SHUTDOWN',
  'CAPACITY_LOSS',
  'DATE_RANGE_WORKSHOPS',
  'WORKING_MODE',
  'RAMP_UP',
  'WBS_LEVEL',
  'WIP_TARGET_OVERRIDE',
  'FIXED_OUTPUT',
  'FIXED_OUTPUT_BATCH',
  'AVOID_SATURDAY',
])

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function factoryScope(value: unknown): FactoryScope {
  const model = record(record(value).factory_model)
  const ids = (key: string, field: string) => Array.isArray(model[key])
    ? (model[key] as unknown[])
      .map((item) => String(record(item)[field] || ''))
      .filter(Boolean)
    : []
  const workshops = Array.from(new Set(ids('workshops', 'workshop_id')))
  const buffers = Array.from(new Set(ids('buffers', 'buffer_id')))
  return {
    workshops,
    buffers,
    wipNodes: [
      ...workshops.map((id) => ({ value: `WORKSHOP:${id}`, label: `车间 · ${id}` })),
      ...buffers.map((id) => ({ value: `BUFFER:${id}`, label: `缓冲区 · ${id}` })),
    ],
    typeclasses: Array.from(new Set(ids('typeclasses', 'typeclass_id'))),
    workingModes: Array.from(new Set(ids('working_modes', 'working_mode_id'))),
  }
}

function defaultValues(
  planningYear: number,
  option: V6ConditionOption,
  scope: FactoryScope,
) {
  const start = `${planningYear}-01-01`
  const end = `${planningYear}-12-31`
  const firstWorkshop = scope.workshops[0]
  return {
    selector_id: option.selector_id,
    start_date: start,
    end_date: end,
    workshop_ids: option.selector_id === 'SHUTDOWN' ? [] : firstWorkshop ? [firstWorkshop] : [],
    working_mode_id: scope.workingModes[0] || 'SINGLE_8P2',
    available_hours_ceiling: 0,
    water_level: 30,
    node_ref: firstWorkshop ? `WORKSHOP:${firstWorkshop}` : undefined,
    target_quantity: 0,
    daily_jph_ceilings: '5, 7, 8, 10',
    workshop_id: firstWorkshop,
    date: start,
    out: 0,
    typeclass_ids: scope.typeclasses,
    used_saturday_days: 0,
    priority_tier: 1,
    items: [{ date: start, workshop_id: firstWorkshop, out: 0 }],
    reason: '',
  }
}

function initialValues(
  planningYear: number,
  option: V6ConditionOption,
  scope: FactoryScope,
  initialValue?: V6ConditionComposerValue | null,
) {
  if (!initialValue) return defaultValues(planningYear, option, scope)
  const values: Record<string, unknown> = {
    ...defaultValues(planningYear, option, scope),
    ...initialValue.params,
    selector_id: initialValue.selectorId,
    reason: initialValue.reason || String(initialValue.params.reason || ''),
  }
  if (option.editor_kind === 'RAMP_UP' && Array.isArray(values.daily_jph_ceilings)) {
    values.daily_jph_ceilings = values.daily_jph_ceilings.join(', ')
  }
  if (option.editor_kind === 'WIP_TARGET_OVERRIDE') {
    values.node_ref = `${String(values.node_type || '')}:${String(values.node_id || '')}`
  }
  if (option.editor_kind === 'FIXED_OUTPUT_BATCH' && Array.isArray(values.items)) {
    values.items = values.items.map((item) => {
      const raw = record(item)
      return { ...record(raw.payload) }
    })
  }
  return values
}

function dateInput(min: string, max: string) {
  return <Input type="date" min={min} max={max} />
}

function DateRange({ planningYear }: { planningYear: number }) {
  const min = `${planningYear}-01-01`
  const max = `${planningYear}-12-31`
  return <Space size={12} align="start" style={{ width: '100%' }}>
    <Form.Item name="start_date" label="起始日期" rules={[{ required: true, message: '请选择起始日期' }]}>
      {dateInput(min, max)}
    </Form.Item>
    <Form.Item name="end_date" label="结束日期" rules={[{ required: true, message: '请选择结束日期' }]}>
      {dateInput(min, max)}
    </Form.Item>
  </Space>
}

function WorkshopSelect({ scope, multiple = true, optional = false }: {
  scope: FactoryScope
  multiple?: boolean
  optional?: boolean
}) {
  return <Form.Item
    name={multiple ? 'workshop_ids' : 'workshop_id'}
    label="车间"
    rules={optional ? [] : [{ required: true, message: '请选择车间' }]}
    extra={optional ? '留空表示全厂。人工选择 AS 不会把 AS 加入自动停线扫描。' : undefined}
  >
    <Select
      mode={multiple ? 'multiple' : undefined}
      getPopupContainer={drawerPopupContainer}
      allowClear={optional}
      options={scope.workshops.map((id) => ({ value: id, label: id }))}
      placeholder={scope.workshops.length ? '选择车间' : '当前 Factory 没有车间'}
      disabled={!scope.workshops.length}
    />
  </Form.Item>
}

function ConditionFields({ option, planningYear, scope }: {
  option: V6ConditionOption
  planningYear: number
  scope: FactoryScope
}) {
  const min = `${planningYear}-01-01`
  const max = `${planningYear}-12-31`
  switch (option.editor_kind) {
    case 'SHUTDOWN':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} optional /></>
    case 'CAPACITY_LOSS':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} /><Form.Item name="available_hours_ceiling" label="可用工时上限" rules={[{ required: true }]}><InputNumber min={0} precision={0} style={{ width: '100%' }} /></Form.Item></>
    case 'DATE_RANGE_WORKSHOPS':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} /></>
    case 'WORKING_MODE':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} optional={option.selector_id === 'FORBID_WORKING_MODE'} /><Form.Item name="working_mode_id" label="工作模式" rules={[{ required: true }]}><Select getPopupContainer={drawerPopupContainer} options={scope.workingModes.map((id) => ({ value: id, label: id }))} /></Form.Item></>
    case 'RAMP_UP':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} optional /><Form.Item name="daily_jph_ceilings" label="逐生产日 JPH 上限" rules={[{ required: true }]}><Input placeholder="例如 5, 7, 8, 10" /></Form.Item></>
    case 'WBS_LEVEL':
      return <><DateRange planningYear={planningYear} /><Form.Item name="water_level" label="WBS 目标水位" rules={[{ required: true }]}><InputNumber min={0} precision={0} style={{ width: '100%' }} /></Form.Item></>
    case 'WIP_TARGET_OVERRIDE':
      return <><DateRange planningYear={planningYear} /><Form.Item name="node_ref" label="节点" rules={[{ required: true, message: '请选择节点' }]}><Select getPopupContainer={drawerPopupContainer} options={scope.wipNodes} /></Form.Item><Form.Item name="target_quantity" label="目标 WIP 总量" rules={[{ required: true }]}><InputNumber min={0} precision={0} style={{ width: '100%' }} /></Form.Item></>
    case 'FIXED_OUTPUT':
      return <><Form.Item name="date" label="日期" rules={[{ required: true }]}>{dateInput(min, max)}</Form.Item><WorkshopSelect scope={scope} multiple={false} /><Form.Item name="out" label="指定 OUT" rules={[{ required: true }]}><InputNumber min={0} precision={0} style={{ width: '100%' }} /></Form.Item></>
    case 'FIXED_OUTPUT_BATCH':
      return <Form.List name="items">
        {(fields, { add, remove }) => <Space direction="vertical" size={10} style={{ width: '100%' }}>
          {fields.map(({ key, ...field }, index) => <Card key={key} size="small" title={`产量条件 ${index + 1}`} extra={fields.length > 1 ? <Button type="text" danger icon={<MinusCircleOutlined />} onClick={() => remove(field.name)}>移除</Button> : null}>
              <Space size={10} align="start" wrap>
                <Form.Item {...field} name={[field.name, 'date']} label="日期" rules={[{ required: true }]}>{dateInput(min, max)}</Form.Item>
                <Form.Item {...field} name={[field.name, 'workshop_id']} label="车间" rules={[{ required: true }]}><Select getPopupContainer={drawerPopupContainer} style={{ width: 120 }} options={scope.workshops.map((id) => ({ value: id, label: id }))} /></Form.Item>
                <Form.Item {...field} name={[field.name, 'out']} label="指定 OUT" rules={[{ required: true }]}><InputNumber min={0} precision={0} /></Form.Item>
              </Space>
            </Card>)}
          <Button type="dashed" block icon={<PlusOutlined />} onClick={() => add({ date: min, workshop_id: scope.workshops[0], out: 0 })}>增加一条产量条件</Button>
        </Space>}
      </Form.List>
    case 'AVOID_SATURDAY':
      return <><DateRange planningYear={planningYear} /><WorkshopSelect scope={scope} /><Form.Item name="typeclass_ids" label="车型" rules={[{ required: true, message: '请选择车型' }]}><Select getPopupContainer={drawerPopupContainer} mode="multiple" options={scope.typeclasses.map((id) => ({ value: id, label: id }))} /></Form.Item><Space size={12} align="start"><Form.Item name="used_saturday_days" label="最多使用周六天数" rules={[{ required: true }]}><InputNumber min={0} precision={0} /></Form.Item><Form.Item name="priority_tier" label="优先级" rules={[{ required: true }]}><InputNumber min={1} max={9} precision={0} /></Form.Item></Space></>
    default:
      return <Alert type="error" showIcon message="该条件尚无可用编辑器" description={`未知 editor_kind：${option.editor_kind}`} />
  }
}

function serialize(option: V6ConditionOption, values: Record<string, unknown>): V6ConditionComposerValue {
  const reason = String(values.reason || '').trim()
  const params: Record<string, unknown> = {}
  const copy = (...keys: string[]) => keys.forEach((key) => {
    if (values[key] !== undefined && values[key] !== null && values[key] !== '') params[key] = values[key]
  })
  switch (option.editor_kind) {
    case 'SHUTDOWN': copy('start_date', 'end_date', 'workshop_ids'); break
    case 'CAPACITY_LOSS': copy('start_date', 'end_date', 'workshop_ids', 'available_hours_ceiling'); break
    case 'DATE_RANGE_WORKSHOPS': copy('start_date', 'end_date', 'workshop_ids'); break
    case 'WORKING_MODE': copy('start_date', 'end_date', 'workshop_ids', 'working_mode_id'); break
    case 'RAMP_UP':
      copy('start_date', 'end_date', 'workshop_ids')
      params.daily_jph_ceilings = String(values.daily_jph_ceilings || '').split(/[,，]/).map((item) => item.trim()).filter(Boolean)
      break
    case 'WBS_LEVEL': copy('start_date', 'end_date', 'water_level'); break
    case 'WIP_TARGET_OVERRIDE': {
      copy('start_date', 'end_date', 'target_quantity')
      const [nodeType, nodeId] = String(values.node_ref || '').split(':', 2)
      params.node_type = nodeType
      params.node_id = nodeId
      break
    }
    case 'FIXED_OUTPUT': copy('date', 'workshop_id', 'out'); break
    case 'FIXED_OUTPUT_BATCH':
      params.items = (Array.isArray(values.items) ? values.items : []).map((item, index) => {
        const row = record(item)
        return {
          object_ref: `v6-output:${String(row.date)}:${String(row.workshop_id)}:${index}`,
          action_type: 'MANUAL_FILLING_ADJUSTMENT',
          payload: { date: row.date, workshop_id: row.workshop_id, out: row.out },
          lock_after_apply: true,
        }
      })
      break
    case 'AVOID_SATURDAY': copy('start_date', 'end_date', 'workshop_ids', 'typeclass_ids', 'used_saturday_days', 'priority_tier'); break
  }
  if (reason && ['SHUTDOWN', 'RAMP_UP'].includes(option.editor_kind)) params.reason = reason
  return {
    selectorType: option.selector_type,
    selectorId: option.selector_id,
    params,
    reason,
  }
}

export function V6ConditionDrawer({
  open,
  planningYear,
  factoryVersionId,
  initialValue,
  defaultSelectorId,
  onClose,
  onApply,
  applyLabel,
}: {
  open: boolean
  planningYear: number
  factoryVersionId: string
  initialValue?: V6ConditionComposerValue | null
  defaultSelectorId?: string
  onClose: () => void
  onApply: (value: V6ConditionComposerValue) => Promise<void>
  applyLabel: string
}) {
  const [form] = Form.useForm()
  const optionsQuery = useQuery({ queryKey: ['v6', 'condition-options'], queryFn: v6Api.conditionOptions, enabled: open, retry: false })
  const factoryQuery = useQuery({ queryKey: ['v6', 'factory', factoryVersionId], queryFn: () => v6Api.factoryVersion(factoryVersionId), enabled: open && Boolean(factoryVersionId), retry: false })
  const options = optionsQuery.data?.options || []
  const scope = useMemo(() => factoryScope(factoryQuery.data), [factoryQuery.data])
  const selectedId = Form.useWatch('selector_id', form)
  const selected = options.find((item) => item.selector_id === selectedId) || options[0]

  useEffect(() => {
    if (!open || !options.length || factoryQuery.isLoading) return
    const id = initialValue?.selectorId || defaultSelectorId || options[0].selector_id
    const option = options.find((item) => item.selector_id === id) || options[0]
    form.resetFields()
    form.setFieldsValue(initialValues(planningYear, option, scope, initialValue))
  }, [defaultSelectorId, factoryQuery.isLoading, form, initialValue, open, options, planningYear, scope])

  const switchOption = (id: string) => {
    const option = options.find((item) => item.selector_id === id)
    if (!option) return
    form.resetFields()
    form.setFieldsValue(defaultValues(planningYear, option, scope))
  }

  return <Drawer title={initialValue ? '编辑 V6.1.4 排产条件' : '新增 V6.1.4 排产条件'} placement="right" width={620} open={open} onClose={onClose} destroyOnClose>
    <Alert
      type="info"
      showIcon
      message="停线与清线由系统自动识别"
      description="初步排产后，系统按 BS1、BS2、PS 分别扫描连续 IN=0 且 OUT=0 的停线窗口并自动执行适用的清线与补线；AS 不参与自动扫描。无需人工添加清线或停线条件来触发识别。"
      style={{ marginBottom: 16 }}
    />
    {(optionsQuery.isError || factoryQuery.isError) && <Alert type="error" showIcon message="条件目录或 Factory 加载失败" description="无法确认后端可执行条件时不允许提交。" style={{ marginBottom: 16 }} />}
    {selected && <Form form={form} layout="vertical" onFinish={async (values) => onApply(serialize(selected, values))}>
      <Form.Item name="selector_id" label="条件类型" rules={[{ required: true }]}>
        <Select
          showSearch
          getPopupContainer={drawerPopupContainer}
          optionFilterProp="label"
          onChange={switchOption}
          options={options.map((option) => ({
            value: option.selector_id,
            label: `${CATEGORY_LABELS[option.category] || option.category} · ${option.label}`,
          }))}
        />
      </Form.Item>
      <Card size="small" style={{ marginBottom: 16 }}>
        <Space wrap>
          <Tag>{CATEGORY_LABELS[selected.category] || selected.category}</Tag>
          <Tag color={SEMANTIC_COLORS[selected.semantic_type] || 'default'}>{selected.semantic_type}</Tag>
        </Space>
        <Typography.Paragraph style={{ margin: '10px 0 0' }}>{selected.description}</Typography.Paragraph>
      </Card>
      <ConditionFields option={selected} planningYear={planningYear} scope={scope} />
      <Form.Item name="reason" label="业务原因（可选）"><Input.TextArea rows={2} placeholder="记录本条件的业务原因" /></Form.Item>
      <Divider />
      <Space>
        <Button onClick={onClose}>取消</Button>
        <Button type="primary" htmlType="submit" disabled={optionsQuery.isError || factoryQuery.isError || !SUPPORTED_EDITORS.has(selected.editor_kind)}>{applyLabel}</Button>
      </Space>
    </Form>}
  </Drawer>
}
