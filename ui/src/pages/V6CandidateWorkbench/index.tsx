import { useState } from 'react'
import { Alert, App as AntdApp, Button, Card, Collapse, Drawer, Empty, Form, Input, List, Space, Statistic, Table, Tabs, Tag, Typography } from 'antd'
import { BranchesOutlined, HistoryOutlined, PlusOutlined, RobotOutlined, SaveOutlined, SyncOutlined, WarningOutlined } from '@ant-design/icons'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { V6ConditionDrawer } from '../../components/V6ConditionDrawer'
import type { V6CandidateIssueDetail, V6ConditionComposerValue, V6ConditionDraft, V6IssueWindowSummary } from '../../types/v6'
import { v6BusinessMessage, v6MonthLabel } from '../../utils/v6Messages'
import { rememberFormalId } from '../../utils/v6FormalViewAuthority'
import { CandidateAnnualPanel } from './CandidateAnnualPanel'
import { CandidateFillingPanel } from './CandidateFillingPanel'
import { hasSafeWindowInformation, SafeHolidayWindowInfo } from './SafeHolidayWindowInfo'

function quantityText(value: unknown): string {
  const number = Number(value)
  return Number.isFinite(number) ? number.toLocaleString('zh-CN') : '—'
}

function issueWindowText(window: V6IssueWindowSummary | null): string {
  if (!window) return '—'
  const dateRange = window.start_date === window.end_date
    ? window.start_date
    : `${window.start_date || '—'} 至 ${window.end_date || '—'}`
  const owner = [window.workshop_id, window.typeclass_id ? `车型 ${window.typeclass_id}` : null]
    .filter(Boolean)
    .join(' / ')
  return [dateRange, owner, window.kind].filter(Boolean).join(' · ')
}

function issueDetailDate(detail: V6CandidateIssueDetail): string | null {
  return detail.date
    || detail.start_date
    || detail.after_window?.start_date
    || detail.before_window?.start_date
    || null
}

function issueDetailKey(detail: V6CandidateIssueDetail, index: number): string {
  return [
    detail.code,
    detail.source,
    detail.change_type,
    detail.date,
    detail.window_id,
    detail.node_id,
    detail.typeclass_id,
    index,
  ].filter((value) => value !== null && value !== undefined).join('-')
}

function proposalPayload(item: V6ConditionDraft['proposal_items'][number]) {
  return {
    proposal_id: item.proposal_id,
    selector_type: item.selector_type,
    selector_id: item.selector_id,
    scope: item.scope,
    params: item.params,
    reason: item.reason,
    referenced_business_ids: item.referenced_business_ids,
  }
}

const conditionReasonLabels: Record<string, string> = {
  CONDITION_DISABLED: '条件已禁用',
  NO_WORKING_DAY_IN_SCOPE: '范围内没有工作日',
  INTENT_MISSING: '偏好条件缺少 Intent',
  COUNTERFACTUAL_PLAN_EQUAL: '移除该条件后最终计划相同',
  COUNTERFACTUAL_PLAN_DIFF: '移除该条件后最终计划发生变化',
  COUNTERFACTUAL_INFEASIBLE_WITHOUT_CONDITION: '移除该条件后没有可行计划',
}

const issueSourceLabels: Record<V6CandidateIssueDetail['source'], string> = {
  EXACT_TRANSITION: '终态校验',
  HOLIDAY_REPAIR: '停复线修复',
  VALIDATION: '物理校验',
  HOLIDAY_DIFF: '窗口变化',
  PROBLEM: '排产问题',
}

const issueChangeLabels: Record<NonNullable<V6CandidateIssueDetail['change_type']>, string> = {
  ADDED: '新增窗口',
  REMOVED: '移除窗口',
  CHANGED: '窗口变化',
}

const formalSaveRule = '保存正式 PP 需同时满足：Session 处于开放状态、当前候选没有硬错误、条件草案已完成应用、日级效果证据完整。存在警告时还需填写知晓原因。'

export function V6CandidateWorkbench() {
  const { message, modal } = AntdApp.useApp()
  const { sessionId = '' } = useParams()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const viewedCandidateId = searchParams.get('candidate')
  const queryClient = useQueryClient()
  const [conditionOpen, setConditionOpen] = useState(false)
  const [conditionDefault, setConditionDefault] = useState<string | undefined>()
  const [editingDraft, setEditingDraft] = useState<V6ConditionDraft | null>(null)
  const [aiText, setAiText] = useState('')
  const [saveOpen, setSaveOpen] = useState(false)
  const [warningReasons, setWarningReasons] = useState<Record<string, string>>({})
  const [activeTab, setActiveTab] = useState('summary')
  const [requestedFillingMonth, setRequestedFillingMonth] = useState<string | null>(null)
  const [form] = Form.useForm()

  const workbenchQuery = useQuery({ queryKey: ['v6', 'workbench', sessionId, viewedCandidateId], queryFn: () => v6Api.workbench(sessionId, viewedCandidateId), retry: false })
  const openSessionsQuery = useQuery({ queryKey: ['v6', 'sessions', 'OPEN'], queryFn: () => v6Api.sessions('OPEN'), staleTime: 10_000, retry: false })
  const queryReadOnly = workbenchQuery.data?.session.status !== 'OPEN'
  const candidateId = (queryReadOnly ? workbenchQuery.data?.viewed_candidate : workbenchQuery.data?.current_candidate)?.candidate_id
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ['v6', 'workbench'] }),
      queryClient.invalidateQueries({ queryKey: ['v6', 'candidate'] }),
      queryClient.invalidateQueries({ queryKey: ['v6', 'sessions'] }),
      queryClient.invalidateQueries({ queryKey: ['v6', 'abandoned-workbench'] }),
    ])
  }

  const createManual = useMutation({
    mutationFn: async (value: V6ConditionComposerValue) => {
      const proposal = { selector_type: value.selectorType, selector_id: value.selectorId, params: value.params, reason: value.reason || '人工结构化条件' }
      if (editingDraft) return v6Api.patchDraft(sessionId, editingDraft.draft_id, editingDraft.draft_revision, [proposal])
      const mergeable = (workbenchQuery.data?.condition_drafts || []).filter((draft) =>
        draft.trace === null && draft.status === 'BUILT',
      )
      if (mergeable.length > 1) throw new Error('请先合并当前全部新增条件')
      if (mergeable.length === 1) {
        const target = mergeable[0]
        return v6Api.patchDraft(
          sessionId,
          target.draft_id,
          target.draft_revision,
          [...target.proposal_items.map(proposalPayload), proposal],
        )
      }
      return v6Api.createManualDraft(sessionId, [proposal])
    },
    onSuccess: async (result) => {
      if (!['DRAFT_BUILT', 'UPDATED', 'NL_NEEDS_CLARIFICATION'].includes(result.outcome)) throw new Error(result.message)
      setConditionOpen(false)
      setEditingDraft(null)
      message.success('条件已加入原子批次，请预览重排影响')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const mergeDrafts = useMutation({
    mutationFn: (drafts: V6ConditionDraft[]) => v6Api.mergeDrafts(
      sessionId,
      drafts.map((draft) => ({
        draft_id: draft.draft_id,
        expected_draft_revision: draft.draft_revision,
      })),
    ),
    onSuccess: async (result) => {
      if (result.outcome !== 'DRAFT_BATCH_BUILT') throw new Error(result.message)
      message.success('全部新增条件已合并为一个原子批次')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const interpret = useMutation({
    mutationFn: () => v6Api.interpretDraft(sessionId, aiText),
    onSuccess: async (result) => {
      if (!['DRAFT_BUILT', 'NL_NEEDS_CLARIFICATION'].includes(result.outcome)) throw new Error(result.message)
      message.success(result.status === 'BUILT' ? 'AI 条件草案已构建' : 'AI 需要补充信息')
      setAiText('')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const previewDraft = useMutation({
    mutationFn: (draft: V6ConditionDraft) => v6Api.previewDraft(sessionId, draft.draft_id, draft.draft_revision),
    onSuccess: async (result) => {
      if (result.outcome !== 'PREVIEWED') throw new Error(result.message)
      message.success('重排影响预览已生成，当前候选未改变')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const applyDraft = useMutation({
    mutationFn: async (draft: V6ConditionDraft) => {
      const grant = await v6Api.approvalGrant(sessionId, draft.draft_id, draft.draft_revision)
      if (!grant.approval_token) throw new Error(grant.message || '后端没有返回一次性批准凭证')
      return v6Api.applyDraft(sessionId, draft.draft_id, draft.draft_revision, grant.approval_token)
    },
    onSuccess: async (result) => {
      if (result.outcome !== 'HUMAN_APPLIED') throw new Error(result.message)
      message.success('全部条件已应用并重排，新 DraftCandidate 已成为当前候选')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const restore = useMutation({
    mutationFn: (candidate: { candidate_id: string }) => v6Api.restoreCandidate(sessionId, candidate.candidate_id, workbenchQuery.data!.session.planning_revision),
    onSuccess: async (result) => {
      if (result.outcome !== 'DRAFT_CANDIDATE_CREATED') throw new Error(result.message)
      message.success('已从历史候选创建恢复分支')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const recoverAbandoned = useMutation({
    mutationFn: async () => {
      if (!candidateId) throw new Error('当前没有可恢复的候选')
      const result = await v6Api.recoverAbandonedDraft(sessionId, candidateId)
      if (result.outcome !== 'DRAFT_SESSION_RECOVERED' || !result.session_id) {
        throw new Error(result.message || '废弃草稿恢复失败')
      }
      return result
    },
    onSuccess: async (result) => {
      message.success('已恢复为新的开放排产')
      await refresh()
      navigate(`/v6/session/${encodeURIComponent(result.session_id!)}`)
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const replan = useMutation({
    mutationFn: () => v6Api.replanHolidayWindows(sessionId, candidateId!, workbenchQuery.data!.session.planning_revision),
    onSuccess: async (result) => {
      if (result.outcome !== 'DRAFT_CANDIDATE_CREATED') throw new Error(result.message)
      message.success('已按 H1∪H2 新窗口再次重排')
      await refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  const save = useMutation({
    mutationFn: async (values: { display_name: string; work_note: string }) => {
      const warnings = workbenchQuery.data?.save_gate.warning_codes_requiring_acknowledgement || []
      const missing = warnings.filter((code) => !warningReasons[code]?.trim())
      if (missing.length) throw new Error(`请填写警告知晓原因：${missing.join(', ')}`)
      return v6Api.saveFormal(sessionId, {
        expected_planning_revision: workbenchQuery.data!.session.planning_revision,
        display_name: values.display_name,
        work_note: values.work_note,
        warning_acknowledgements: warnings.map((warning_code) => ({ warning_code, reason: warningReasons[warning_code].trim() })),
      })
    },
    onSuccess: async (result) => {
      if (result.outcome !== 'FORMAL_PP_SAVED' || !result.formal_pp_id) throw new Error(result.message)
      message.success('正式 PP 已保存，Session 已关闭')
      await refresh()
      rememberFormalId(result.formal_pp_id)
      navigate(`/v6/formal-pp/${encodeURIComponent(result.formal_pp_id)}/annual`)
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  if (workbenchQuery.isLoading) return <PageState kind="loading" rows={8} />
  if (workbenchQuery.isError) return <PageState kind="system-error" error={workbenchQuery.error} onRetry={() => void workbenchQuery.refetch()} />
  const workbench = workbenchQuery.data
  if (!workbench) return <PageState kind="empty" title="没有 V6.1.4 工作台数据" />
  const isReadOnly = workbench.session.status !== 'OPEN'
  const candidate = isReadOnly
    ? (workbench.viewed_candidate || workbench.current_candidate)
    : workbench.current_candidate
  if (!candidate) return <div className="page-container"><PageHeader title="V6.1.4 候选工作台" /><PageState kind="business-blocked" title="Session 尚无 DraftCandidate" reasons={['请重新执行后端候选生成；系统不会把空结果当作正式计划。']} /></div>

  const initialCondition = editingDraft?.proposal_items[0]
    ? {
        selectorType: editingDraft.proposal_items[0].selector_type as 'ACTION' | 'INTENT',
        selectorId: editingDraft.proposal_items[0].selector_id,
        params: editingDraft.proposal_items[0].params,
        reason: editingDraft.proposal_items[0].reason,
      }
    : null
  const conditionRows = isReadOnly
    ? []
    : workbench.condition_drafts.filter((draft) => draft.status !== 'USER_REJECTED')
  const conditionExecutionRows = candidate.condition_results || []
  const mergeableDrafts = conditionRows.filter((draft) =>
    draft.trace === null && ['BUILT', 'PREVIEWED'].includes(draft.status),
  )
  const hardSaveBlocker = workbench.save_gate.blockers.some((item) =>
    ['HARD_ERRORS', 'HARD_VALIDATION_FAILED'].includes(item.code),
  )
  const saveBlockerGuidance = workbench.save_gate.blockers.map((item) => {
    if (item.code === 'OPEN_CONDITION_DRAFT') {
      return mergeableDrafts.length > 1
        ? '检测到多个独立条件草案。请先合并全部新增条件，再预览重排影响并应用重排。'
        : '存在尚未应用的条件草案。请先预览重排影响，再应用条件并生成新候选。'
    }
    if (['HARD_ERRORS', 'HARD_VALIDATION_FAILED'].includes(item.code)) {
      return '请打开“问题 / 警告”查看具体硬错误，修正输入或适用的排产条件后重新生成候选。'
    }
    if (item.code === 'SESSION_NOT_OPEN') return '该 Session 已关闭或废弃，不能继续保存。'
    if (item.code === 'NO_CURRENT_CANDIDATE') return '当前 Session 没有可保存的 DraftCandidate。'
    if (item.code === 'EFFECT_EVIDENCE_NOT_EVALUATED') return '当前候选缺少权威日级效果证据，需要重新生成候选。'
    const business = v6BusinessMessage(item.code)
    return `${business.title}：${business.suggestion}`
  }).join('；') || '当前候选不能保存。'
  const hasHolidayChange = candidate.warning_codes.includes('HOLIDAY_WINDOW_CHANGED')
  const safeWindowInformation = hasSafeWindowInformation(candidate.holiday_reconciliation)
  const openFillingMonth = (month: string) => {
    setRequestedFillingMonth(month)
    setActiveTab('filling')
  }
  const showHistoricalCandidate = (nextCandidateId: string) => {
    const next = new URLSearchParams(searchParams)
    next.set('candidate', nextCandidateId)
    setSearchParams(next)
    setActiveTab('summary')
  }
  const confirmAbandonedRecovery = () => {
    const snapshots = workbench.session.input_bundle.business_id_snapshots
    const label = (kind: string, fallback = '—') => snapshots.find((item) => item.kind === kind)?.business_id || fallback
    modal.confirm({
      title: `恢复 Draft #${candidate.candidate_revision} 为新排产？`,
      width: 620,
      content: <Space direction="vertical" size={10} style={{ width: '100%', marginTop: 12 }}>
        <Alert type="warning" showIcon message="严格使用原候选的冻结版本" description="系统不会替换成当前 ACTIVE 版本；将重新执行当前 Preflight 和计划校验，原废弃 Session 保持不变。" />
        <Typography.Text>PR：{label('PR')}</Typography.Text>
        <Typography.Text>WS：{workbench.session.input_bundle.ws_version_id ? label('WS') : 'NOT_EVALUATED'}</Typography.Text>
        <Typography.Text>Factory：{label('FACTORY')}</Typography.Text>
        <Typography.Text>Calendar：{label('CALENDAR')}</Typography.Text>
        <Typography.Text>Initial / WIP：{label('INITIAL_STATE')} / {label('WIP_POLICY')}</Typography.Text>
        <Typography.Text>Actual / 父 Formal：{workbench.session.input_bundle.actual_revision_id ? label('ACTUAL') : 'NOT_EVALUATED'} / {workbench.session.parent_formal_pp_id ? '已冻结绑定' : 'NOT_EVALUATED'}</Typography.Text>
      </Space>,
      okText: '创建新的开放排产',
      cancelText: '取消',
      onOk: () => recoverAbandoned.mutateAsync(),
    })
  }

  const summary = <div className="v6-summary-grid">
    <Statistic title="年度 PR" value={candidate.pr_total} />
    <Statistic title="年度 PP" value={candidate.pp_total} />
    <Statistic title="Production Day" value={candidate.production_day_count} />
    <Statistic title="Pending Day" value={candidate.pending_day_count} />
    <Card title="假期与局部修复" size="small"><p>识别窗口：{candidate.holiday_windows.length}</p><p>警告：{candidate.warning_codes.length}</p><SafeHolidayWindowInfo evidence={candidate.holiday_reconciliation} onOpenMonth={openFillingMonth} />{!isReadOnly && hasHolidayChange && !safeWindowInformation && <Button icon={<SyncOutlined />} loading={replan.isPending} onClick={() => replan.mutate()}>按新窗口再次重排</Button>}</Card>
    <Card title={isReadOnly ? '废弃草稿状态' : '保存门禁'} size="small">{isReadOnly ? <><Tag>只读</Tag><Typography.Paragraph type="secondary" style={{ margin: '10px 0 4px' }}>原 Session 已放弃，不能修改或直接保存为正式 PP。恢复后将在新的 OPEN Session 中继续。</Typography.Paragraph></> : <><Tag color={workbench.save_gate.technical_save_allowed ? 'success' : 'error'}>{workbench.save_gate.technical_save_allowed ? '技术门禁通过' : '当前不可保存'}</Tag><Typography.Paragraph type="secondary" style={{ margin: '10px 0 4px' }}>{formalSaveRule}</Typography.Paragraph><List size="small" dataSource={workbench.save_gate.blockers} renderItem={(item) => <List.Item><Typography.Text type="danger">{v6BusinessMessage(item.code).title}</Typography.Text></List.Item>} /></>}</Card>
  </div>

  const conditionPanel = <div>
    {!isReadOnly && !workbench.save_gate.technical_save_allowed && <Alert type="warning" showIcon style={{ marginBottom: 14 }} message="当前候选不能保存" description={saveBlockerGuidance} action={hardSaveBlocker ? <Button size="small" onClick={() => setActiveTab('issues')}>查看问题 / 警告</Button> : undefined} />}
    {candidate.condition_evidence_status === 'NOT_EVALUATED' ? <Alert type="warning" showIcon style={{ marginBottom: 14 }} message="历史 Candidate 缺少条件执行证据" description="系统不会从计划差异猜测回填，请基于原输入生成新 Candidate。" /> : <Card size="small" title={`当前候选条件执行结果（${conditionExecutionRows.length}）`} style={{ marginBottom: 14 }}><Table rowKey="condition_id" size="small" pagination={false} dataSource={conditionExecutionRows} locale={{ emptyText: '当前候选没有输入条件' }} columns={[
      { title: '条件', render: (_, row) => <div><strong>{row.plugin_type}</strong><div className="muted">{row.condition_id.slice(0, 8)}</div></div> },
      { title: '执行状态', dataIndex: 'status', render: (value) => <Tag color={value === 'APPLIED' ? 'blue' : value === 'BLOCKED' ? 'error' : 'default'}>{value === 'APPLIED' ? '已适用' : value === 'BLOCKED' ? '被阻断' : '不适用'}</Tag> },
      { title: '计划影响', dataIndex: 'plan_impact', render: (value) => <Tag color={value === 'PLAN_CHANGED' ? 'success' : 'default'}>{value === 'PLAN_CHANGED' ? '已改变计划' : '计划未变化'}</Tag> },
      { title: '原因', dataIndex: 'reason_code', render: (value) => <Typography.Text title={value}>{conditionReasonLabels[value] || value || '—'}</Typography.Text> },
      { title: '日级证据', render: (_, row) => `${row.effect_ids.length} 条` },
    ]} /></Card>}
    {isReadOnly ? <Alert type="info" showIcon message="仅展示已经生效的条件结果" description="未应用的 ConditionDraft 不属于恢复范围；请恢复为新的开放排产后再新增或修改条件。" /> : <><Space style={{ marginBottom: 14 }}><Button type="primary" icon={<PlusOutlined />} onClick={() => { setEditingDraft(null); setConditionDefault(undefined); setConditionOpen(true) }}>新增结构化条件</Button>{mergeableDrafts.length > 1 && <Button loading={mergeDrafts.isPending} onClick={() => mergeDrafts.mutate(mergeableDrafts)}>合并全部新增条件</Button>}{workbench.session.generation_mode === 'ROLLING_FROM_FORMAL_PP' && <Tag color="blue">Rolling 可使用 AI ConditionDraft</Tag>}</Space>
    {workbench.session.generation_mode === 'ROLLING_FROM_FORMAL_PP' && <Card size="small" title={<Space><RobotOutlined />AI 自然语言条件</Space>} style={{ marginBottom: 14 }}><Input.TextArea rows={3} value={aiText} onChange={(event) => setAiText(event.target.value)} placeholder="输入本轮 Rolling 条件；含糊内容会进入 NEEDS_CLARIFICATION，不会猜测执行。" /><Button style={{ marginTop: 8 }} loading={interpret.isPending} disabled={!aiText.trim()} onClick={() => interpret.mutate()}>解释为原子条件草案</Button></Card>}
    <Table rowKey="draft_id" pagination={false} dataSource={conditionRows} columns={[
      { title: '草案', render: (_, row) => <div><strong>{row.raw_text === 'MERGED_MANUAL_CONDITION_BATCH' ? '结构化条件批次' : row.raw_text === 'MANUAL_STRUCTURED_CONDITION' ? '结构化人工条件' : row.raw_text}</strong><div className="muted">{row.draft_id.slice(0, 8)} · rev.{row.draft_revision}</div></div> },
      { title: '状态', dataIndex: 'status', render: (value) => <Tag color={value === 'HUMAN_APPLIED' ? 'success' : value === 'NEEDS_CLARIFICATION' ? 'warning' : 'processing'}>{value}</Tag> },
      { title: '条件', render: (_, row) => row.proposal_items.map((item) => item.selector_id).join(', ') || row.missing_information.join(', ') },
      { title: '操作', render: (_, row) => <Space wrap><Button size="small" onClick={() => { setEditingDraft(row); setConditionOpen(true) }} disabled={row.status === 'HUMAN_APPLIED' || row.proposal_items.length > 1}>编辑</Button><Button size="small" onClick={() => previewDraft.mutate(row)} loading={previewDraft.isPending} disabled={row.status !== 'BUILT'}>预览重排影响</Button><Button size="small" type="primary" onClick={() => applyDraft.mutate(row)} loading={applyDraft.isPending} disabled={row.status !== 'PREVIEWED'}>应用全部条件并重排</Button></Space> },
    ]} /></>}
  </div>

  const issueItems = [
    ...candidate.hard_error_codes.map((code) => ({ severity: 'error', code })),
    ...candidate.warning_codes.map((code) => ({ severity: 'warning', code })),
  ]
  const issueDetailsByCode = (candidate.issue_details || []).reduce<Record<string, V6CandidateIssueDetail[]>>((result, detail) => {
    result[detail.code] = [...(result[detail.code] || []), detail]
    return result
  }, {})
  const openIssueMonth = (detail: V6CandidateIssueDetail) => {
    const month = issueDetailDate(detail)?.slice(0, 7)
    if (!month) return
    setRequestedFillingMonth(month)
    setActiveTab('filling')
  }
  const issuesPanel = <><SafeHolidayWindowInfo evidence={candidate.holiday_reconciliation} onOpenMonth={openFillingMonth} /><div className="v6-two-column">
    <Card title="硬错误与警告"><List dataSource={issueItems} locale={{ emptyText: '当前没有硬错误或警告' }} renderItem={(item) => {
      const business = v6BusinessMessage(item.code)
      const details = issueDetailsByCode[item.code] || []
      return <List.Item><div style={{ width: '100%' }}><Space wrap><Tag color={item.severity === 'error' ? 'error' : 'warning'}>{business.title}</Tag><Typography.Text code type="secondary">{item.code}</Typography.Text></Space><Typography.Paragraph style={{ margin: '8px 0 4px' }}>{business.description}</Typography.Paragraph><Typography.Text type="secondary">建议：{business.suggestion}</Typography.Text>{details.length > 0 && <Collapse
        ghost
        size="small"
        style={{ marginTop: 8 }}
        items={[{
          key: item.code,
          label: `影响明细 ${details.length} 条`,
          children: <List
            size="small"
            dataSource={details}
            renderItem={(detail, index) => {
              const detailDate = issueDetailDate(detail)
              const hasWindow = Boolean(detail.window_id || detail.before_window || detail.after_window)
              const nodeText = [
                detail.workshop_id ? `窗口车间 ${detail.workshop_id}` : null,
                detail.node_id ? `问题节点 ${detail.node_id}` : null,
                detail.quantity_scope === 'NODE_TOTAL' ? '节点总量 / 全车型合计' : null,
                detail.typeclass_id
                  ? `${detail.quantity_scope === 'NODE_TOTAL' ? '触发车型' : '车型'} ${detail.typeclass_id}`
                  : detail.source === 'VALIDATION' ? '全部车型合计' : null,
              ].filter(Boolean).join(' · ')
              return <List.Item key={issueDetailKey(detail, index)}>
                <div style={{ width: '100%' }}>
                  <Space wrap>
                    <Tag>{issueSourceLabels[detail.source]}</Tag>
                    {detail.change_type && <Tag color="gold">{issueChangeLabels[detail.change_type]}</Tag>}
                    {detail.start_date && detail.end_date && <Tag color="blue">窗口 {detail.start_date} 至 {detail.end_date}</Tag>}
                    {detail.date && <Tag color="purple">问题日 {detail.date}</Tag>}
                    {detail.window_id && <Typography.Text code>窗口 {detail.window_id.slice(0, 8)}</Typography.Text>}
                  </Space>
                  {detail.change_type && <Typography.Paragraph style={{ margin: '8px 0 4px' }}>原窗口：{issueWindowText(detail.before_window)}<br />新窗口：{issueWindowText(detail.after_window)}</Typography.Paragraph>}
                  {nodeText && <Typography.Paragraph style={{ margin: '8px 0 4px' }}>{nodeText}</Typography.Paragraph>}
                  {(detail.target !== null || detail.actual !== null) && <Typography.Paragraph style={{ margin: '4px 0' }}>目标 / 上限：<strong>{quantityText(detail.target)}</strong>；实际：<strong>{quantityText(detail.actual)}</strong></Typography.Paragraph>}
                  {!hasWindow && detail.source === 'VALIDATION' && <Typography.Text type="secondary">日级缓冲区校验，不适用停线窗口。</Typography.Text>}
                  {detail.detail && <Typography.Paragraph type="secondary" style={{ margin: '4px 0' }}>技术明细：{detail.detail}</Typography.Paragraph>}
                  {detailDate && <Button size="small" onClick={() => openIssueMonth(detail)}>查看该月 Filling</Button>}
                </div>
              </List.Item>
            }}
          />,
        }]}
      />}</div></List.Item>
    }} /></Card>
    <Card title="排产问题"><Table size="small" rowKey={(row) => `${row.code}-${row.month}-${row.typeclass_id}`} pagination={false} scroll={{ x: 920 }} dataSource={candidate.problems} columns={[
      { title: '月份', dataIndex: 'month', width: 100, render: (value) => v6MonthLabel(value) },
      { title: '车型', dataIndex: 'typeclass_id', width: 70 },
      { title: '问题', dataIndex: 'code', render: (code) => <div><strong>{v6BusinessMessage(code).title}</strong><div className="muted">{code}</div></div> },
      { title: '需求', dataIndex: 'required', width: 80, align: 'right' as const, render: quantityText },
      { title: '可实现', dataIndex: 'realizable', width: 80, align: 'right' as const, render: quantityText },
      { title: '缺口', dataIndex: 'gap', width: 80, align: 'right' as const, render: (value) => <Typography.Text type="danger">{quantityText(value)}</Typography.Text> },
      { title: '详情', dataIndex: 'detail', width: 220, render: (value) => value || '—' },
      { title: '处理建议', dataIndex: 'code', render: (code) => v6BusinessMessage(code).suggestion },
    ]} /></Card>
  </div></>

  return <div className="page-container v6-workbench-page">
    <PageHeader
      title={workbench.session.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产候选工作台' : 'Rolling 候选工作台'}
      subtitle={isReadOnly ? `废弃草稿 · Draft #${candidate.candidate_revision}` : `Session ${sessionId} · 当前 Draft #${candidate.candidate_revision}`}
      actions={isReadOnly
        ? <Button
            type="primary"
            icon={<BranchesOutlined />}
            disabled={Boolean(openSessionsQuery.data?.length) || openSessionsQuery.isLoading}
            loading={recoverAbandoned.isPending}
            onClick={confirmAbandonedRecovery}
          >恢复为新排产</Button>
        : <Space><Button icon={<PlusOutlined />} onClick={() => { setEditingDraft(null); setConditionDefault(undefined); setConditionOpen(true) }}>新增排产条件</Button><Button type="primary" icon={<SaveOutlined />} onClick={() => setSaveOpen(true)}>保存正式 PP</Button></Space>}
    />
    {isReadOnly
      ? <Alert
          type="warning"
          showIcon
          style={{ marginBottom: 12 }}
          message="原 Session 已放弃，当前工作台只读"
          description={openSessionsQuery.data?.length ? '已有进行中的排产；请先继续、保存或放弃它，再恢复此候选。' : '恢复会严格复制此候选的冻结输入和原计划，创建新的 OPEN Session；原记录不会改变。'}
          action={openSessionsQuery.data?.length ? <Button onClick={() => navigate(`/v6/session/${encodeURIComponent(openSessionsQuery.data![0].session_id)}`)}>继续当前排产</Button> : undefined}
        />
      : <Alert type="info" showIcon style={{ marginBottom: 12 }} message="当前 DraftCandidate 已自动保存" description="该候选保存在当前 OPEN Session 中；关闭或重新打开浏览器不会删除。只有保存正式 PP 才会进入正式 PP 库。" />}
    <Tabs activeKey={activeTab} onChange={setActiveTab} items={[
      { key: 'summary', label: '候选摘要', children: summary },
      { key: 'annual', label: '年度总览', children: <CandidateAnnualPanel candidateId={candidate.candidate_id} issueCount={candidate.problems.length + candidate.warning_codes.length + candidate.hard_error_codes.length} onOpenMonth={(month) => { setRequestedFillingMonth(month); setActiveTab('filling') }} /> },
      { key: 'filling', label: '月度 Filling', children: <CandidateFillingPanel candidateId={candidate.candidate_id} candidateRevision={candidate.candidate_revision} months={Array.from(new Set([...Object.keys(candidate.pr_by_month), ...Object.keys(candidate.pp_by_month)])).sort()} requestedMonth={requestedFillingMonth} onRequestedMonthHandled={() => setRequestedFillingMonth(null)} onSpecifyOutput={isReadOnly ? undefined : () => { setEditingDraft(null); setConditionDefault('MANUAL_FILLING_ADJUSTMENT'); setConditionOpen(true) }} /> },
      { key: 'conditions', label: `条件${isReadOnly ? '' : ' / AI'} (${isReadOnly ? conditionExecutionRows.length : conditionRows.length})`, children: conditionPanel },
      { key: 'issues', label: <Space><WarningOutlined />问题 / 警告 ({candidate.problems.length + candidate.warning_codes.length + candidate.hard_error_codes.length})</Space>, children: issuesPanel },
      { key: 'history', label: <Space><HistoryOutlined />候选历史</Space>, children: <Table rowKey="candidate_id" pagination={false} dataSource={workbench.candidate_history} columns={[
        { title: 'Revision', dataIndex: 'candidate_revision', width: 90 },
        { title: '候选', render: (_, row) => <Space><span>Draft #{row.candidate_revision}</span>{row.is_current && <Tag color="blue">{isReadOnly ? '放弃时当前' : '当前'}</Tag>}{row.candidate_id === candidate.candidate_id && <Tag color="processing">正在查看</Tag>}</Space> },
        { title: '生成原因', dataIndex: 'generation_reason' },
        { title: '验证', dataIndex: 'validation_status' },
        { title: '时间', dataIndex: 'created_at' },
        { title: '操作', render: (_, row) => isReadOnly
          ? <Button size="small" disabled={row.candidate_id === candidate.candidate_id} onClick={() => showHistoricalCandidate(row.candidate_id)}>查看此候选</Button>
          : <Button size="small" icon={<BranchesOutlined />} disabled={row.is_current} loading={restore.isPending} onClick={() => restore.mutate(row)}>从此候选恢复</Button> },
      ]} /> },
    ]} />
    {!isReadOnly && <V6ConditionDrawer open={conditionOpen} planningYear={Number(Object.keys(candidate.pr_by_month)[0]?.slice(0, 4)) || new Date().getFullYear()} factoryVersionId={workbench.session.input_bundle.factory_version_id} initialValue={initialCondition} defaultSelectorId={conditionDefault} onClose={() => { setConditionOpen(false); setEditingDraft(null); setConditionDefault(undefined) }} applyLabel={editingDraft ? '更新草案' : '创建草案'} onApply={async (value) => { await createManual.mutateAsync(value) }} />}
    {!isReadOnly && <Drawer title="Save / Promote · 保存正式 PP" open={saveOpen} onClose={() => setSaveOpen(false)} width={520}>
      <Typography.Paragraph type="secondary">{formalSaveRule}</Typography.Paragraph>
      {workbench.save_gate.unsafe_demo_override && <Alert type="error" showIcon message="仅演示环境绕过硬校验" description={`该候选仍有硬错误：${workbench.save_gate.unsafe_demo_hard_error_codes.join('、') || '验证状态为 ERROR'}。保存结果会强制标记为“不可信演示”，不得用于生产或验收。`} style={{ marginBottom: 12 }} />}
      <Alert type={workbench.save_gate.unsafe_demo_override ? 'warning' : (workbench.save_gate.technical_save_allowed ? 'success' : 'error')} showIcon message={workbench.save_gate.unsafe_demo_override ? '演示保存门禁已启用' : (workbench.save_gate.technical_save_allowed ? '后端技术门禁已通过' : '当前候选不能保存')} description={workbench.save_gate.technical_save_allowed ? '请填写正式名称、总体备注和全部警告知晓原因。' : saveBlockerGuidance} action={!workbench.save_gate.technical_save_allowed && hardSaveBlocker ? <Button size="small" onClick={() => { setSaveOpen(false); setActiveTab('issues') }}>查看问题 / 警告</Button> : undefined} />
      {workbench.save_gate.warning_codes_requiring_acknowledgement.map((code) => <Card key={code} size="small" title={<Space><span>{v6BusinessMessage(code).title}</span><Typography.Text code type="secondary">{code}</Typography.Text></Space>} style={{ marginTop: 12 }}><Input.TextArea rows={2} value={warningReasons[code] || ''} onChange={(event) => setWarningReasons((current) => ({ ...current, [code]: event.target.value }))} placeholder="填写为什么仍选择保存当前候选" /></Card>)}
      <Form form={form} layout="vertical" style={{ marginTop: 16 }} onFinish={(values) => save.mutate(values)}><Form.Item name="display_name" label="正式 PP 名称" rules={[{ required: true }]}><Input /></Form.Item><Form.Item name="work_note" label="总体备注" rules={[{ required: true }]}><Input.TextArea rows={4} /></Form.Item><Button type="primary" htmlType="submit" block icon={<SaveOutlined />} loading={save.isPending} disabled={!workbench.save_gate.technical_save_allowed}>保存正式 PP 并关闭 Session</Button></Form>
    </Drawer>}
  </div>
}
