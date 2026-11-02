import { CloseOutlined, CopyOutlined, InfoCircleOutlined, LockOutlined, TagOutlined } from '@ant-design/icons'
import { Button, Card, Descriptions, Divider, Drawer, Empty, Space, Table, Tabs, Tag, Typography } from 'antd'
import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../../api/planning'
import { QueryEmpty, QueryError, QueryLoading } from '../../components/ApiState'
import { StatusTag } from '../../components/StatusTag'
import type { MonthlyDay } from '../../types/api'
import { displayValue, formatDate } from '../../utils/format'

export function WhyDrawer({ planVersionId, day, objectRef, onClose }: { planVersionId: string; day: MonthlyDay | null; objectRef: string | null; onClose: () => void }) {
  const [activeTab, setActiveTab] = useState('detail')
  const query = useQuery({
    queryKey: ['explanation', planVersionId, objectRef],
    queryFn: () => api.explanation(planVersionId, objectRef as string),
    enabled: Boolean(day && objectRef),
  })
  const open = Boolean(day)
  const flowRows = day ? [
    { key: 'BS1', stage: 'BS1', in: day.bs1_in, out: day.bs1_out, wip: day.bs1_eod },
    { key: 'BS2', stage: 'BS2', in: day.bs2_in, out: day.bs2_out, wip: day.bs2_eod },
    { key: 'WBS', stage: 'WBS', in: day.wbs_in, out: day.wbs_out, wip: day.wbs_eod },
    { key: 'PS', stage: 'PS', in: day.ps_in, out: day.ps_out, wip: day.ps_eod },
    { key: 'PBS', stage: 'PBS', in: day.pbs_in, out: day.pbs_out, wip: day.pbs_eod },
    { key: 'AS', stage: 'AS', in: day.as_in, out: day.as_out, wip: day.as_eod },
  ] : []

  const tabItems = [
    {
      key: 'detail',
      label: '当日详情',
      children: (
        <div className="why-grid">
          <Card title={<span>当日计划流转（WIP） <InfoCircleOutlined /></span>} size="small" className="span-two">
            <Table size="small" pagination={false} rowKey="key" dataSource={flowRows} columns={[{ title: '缓冲层', dataIndex: 'stage' }, { title: 'IN', dataIndex: 'in', render: (value) => displayValue(value) }, { title: 'OUT', dataIndex: 'out', render: (value) => displayValue(value) }, { title: 'WIP', dataIndex: 'wip', render: (value) => displayValue(value) }]} />
          </Card>
          <Card title="成品库存（WIP）" size="small"><Descriptions column={1} size="small"><Descriptions.Item label="finished_inventory_eod">{displayValue(day?.finished_inventory_eod ?? null)}</Descriptions.Item></Descriptions></Card>
          <Card title="班次 / 工时" size="small"><Descriptions column={1} size="small"><Descriptions.Item label="Working Mode">{day?.working_mode || '—'}</Descriptions.Item><Descriptions.Item label="JPH">{displayValue(day?.jph ?? null)}</Descriptions.Item><Descriptions.Item label="Hours">{displayValue(day?.hours ?? null)}</Descriptions.Item></Descriptions></Card>
          <Card title="生产块" size="small"><Descriptions column={1} size="small"><Descriptions.Item label="production_block_ref">{day?.production_block_ref || '—'}</Descriptions.Item></Descriptions></Card>
          <Card title="技术信息" size="small">
            <Descriptions column={1} size="small">
              <Descriptions.Item label="object_ref"><Typography.Text copyable={Boolean(objectRef)}>{objectRef || '—'}</Typography.Text></Descriptions.Item>
              <Descriptions.Item label="explanation_ref">{day?.explanation_ref || '—'}</Descriptions.Item>
              <Descriptions.Item label="field_refs 数量">{day?.field_refs?.length || 0}</Descriptions.Item>
            </Descriptions>
          </Card>
        </div>
      ),
    },
    {
      key: 'accumulate',
      label: '累计与 Typeclass',
      children: (
        <div className="why-grid">
          <Card title="Typeclass 指标（当日）" size="small">
            <MetricList metrics={day?.typeclass_metrics?.flatMap((item) => item.metrics.map((metric) => ({ label: `${item.typeclass_id} · ${metric.display_name}`, value: displayValue(metric.value, metric.unit) }))) || []} empty="后端未返回 Typeclass 指标" />
          </Card>
          <Card title="累计指标（截至当日）" size="small">
            <MetricList metrics={day?.accumulate_metrics?.map((metric) => ({ label: `${metric.typeclass_id || '—'} · ${metric.display_name}`, value: displayValue(metric.value, metric.unit) })) || []} empty="后端未返回累计指标" />
          </Card>
        </div>
      ),
    },
    {
      key: 'impact',
      label: '影响与原因',
      children: (
        <div>
          {query.isLoading && <QueryLoading />}
          {query.isError && <QueryError error={query.error} onRetry={() => void query.refetch()} />}
          {query.data && (
            <>
              <Card size="small" className="explanation-head">
                <Typography.Title level={5}>{query.data.headline}</Typography.Title>
                <Typography.Paragraph>{query.data.decision}</Typography.Paragraph>
              </Card>
              <ExplanationList title="原因链 (reason_chain)" values={query.data.reason_chain} />
              <ExplanationList title="硬约束 (hard_constraints)" values={query.data.hard_constraints} />
              <ExplanationList title="业务意图 (business_intents)" values={query.data.business_intents} />
              <ExplanationList title="应用效果 (applied_effects)" values={query.data.applied_effects} />
              <Card size="small" className="explanation-list" title="拒绝的候选 (rejected_candidates)">
                {query.data.rejected_candidates?.length ? (
                  <Table
                    size="small"
                    pagination={false}
                    rowKey={(row, index) => `${row.candidate_value}-${index}`}
                    dataSource={query.data.rejected_candidates}
                    columns={[
                      { title: '候选值', dataIndex: 'candidate_value' },
                      { title: '拒绝原因（确定性）', dataIndex: 'reason' },
                    ]}
                  />
                ) : (
                  <span className="muted">后端未返回</span>
                )}
              </Card>
              <ExplanationList title="算法来源 (algorithm_provenance)" values={query.data.algorithm_provenance} />
              <ExplanationList title="证据引用 (evidence_refs)" values={query.data.evidence_refs} copy />
            </>
          )}
          {!query.isLoading && !query.isError && !query.data && !objectRef && (
            <QueryEmpty description="该日期没有可用的 explanation_ref，前端不生成解释" />
          )}
        </div>
      ),
    },
    {
      key: 'history',
      label: '操作记录',
      children: (
        <Card size="small">
          <Empty description="暂无操作记录" />
        </Card>
      ),
    },
  ]

  return <Drawer open={open} onClose={onClose} width={760} closeIcon={<CloseOutlined />} title={<div><div className="drawer-title">日明细 / Why</div><div className="muted">计划版本：{planVersionId.slice(0, 8)} · 日期：{day ? formatDate(day.date) : '—'}</div></div>}>
    {!day ? <Empty description="未选择日期" /> : <div className="why-drawer-content">
      <Card className="drawer-summary" size="small">
        <Descriptions column={3} size="small" colon={false}>
          <Descriptions.Item label={<><span className="summary-icon"><InfoCircleOutlined /></span>日历状态</>}><StatusTag value={day.calendar_state} /></Descriptions.Item>
          <Descriptions.Item label={<><span className="summary-icon"><LockOutlined /></span>锁定状态 / 来源</>}><Space direction="vertical" size={0}><StatusTag value={day.lock_state} /><span className="muted">{day.lock_source || '后端未返回来源'}</span></Space></Descriptions.Item>
          <Descriptions.Item label={<><span className="summary-icon"><TagOutlined /></span>原因引用</>}><Typography.Text copyable={Boolean(objectRef)} ellipsis={{ tooltip: objectRef || 'Contract 未返回 explanation_ref' }}>{objectRef || '—'}</Typography.Text></Descriptions.Item>
        </Descriptions>
      </Card>
      <Tabs activeKey={activeTab} onChange={setActiveTab} items={tabItems} />
      <div className="technical-ref"><span>object_ref</span><Typography.Text copyable={Boolean(objectRef)}>{objectRef || 'Contract 未返回'}</Typography.Text><span>explanation_ref</span><Typography.Text>{query.data?.object_ref || '—'}</Typography.Text></div>
    </div>}
  </Drawer>
}

function ExplanationList({ title, values, copy = false }: { title: string; values: string[]; copy?: boolean }) {
  return <Card size="small" className="explanation-list" title={title}>
    {values.length ? <ul>{values.map((value, index) => <li key={`${title}-${index}`}>{copy ? <Typography.Text copyable>{value}</Typography.Text> : value}</li>)}</ul> : <span className="muted">后端未返回</span>}
  </Card>
}

function MetricList({ metrics, empty }: { metrics: { label: string; value: string }[]; empty: string }) {
  if (!metrics.length) return <span className="muted">{empty}</span>
  return <div className="metric-list">{metrics.map((metric, index) => <div key={`${metric.label}-${index}`}><span>{metric.label}</span><strong>{metric.value}</strong></div>)}</div>
}
