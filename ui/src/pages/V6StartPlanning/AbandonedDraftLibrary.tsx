import { BranchesOutlined, EyeOutlined, InfoCircleOutlined, PlayCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Collapse, Descriptions, Empty, Modal, Space, Table, Tag, Typography, message } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { v6Api } from '../../api/v6'
import { PageState } from '../../components/PageState'
import type { V6CandidateHistoryItem, V6Session } from '../../types/v6'

const modeLabel = (session: V6Session) => (
  session.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产' : 'Rolling'
)

function snapshotLabel(session: V6Session, kind: string, fallback = '—'): string {
  return session.input_bundle.business_id_snapshots.find((item) => item.kind === kind)?.business_id || fallback
}

function planningYear(session: V6Session): string {
  const labels = session.input_bundle.business_id_snapshots.map((item) => item.business_id).join(' ')
  return labels.match(/(?:^|\D)(20\d{2})(?:\D|$)/)?.[1] || '年份待核对'
}

function displayDate(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString('zh-CN', { hour12: false })
}

function draftName(session: V6Session): string {
  return session.work_note?.trim()
    || `${modeLabel(session)} · ${planningYear(session)} · ${displayDate(session.closed_at)}`
}

function validationTag(status: string) {
  const color = status === 'PASS' ? 'success' : status === 'WARNING' ? 'warning' : 'error'
  return <Tag color={color}>{status}</Tag>
}

function RecoveryBindings({ session }: { session: V6Session }) {
  return <Descriptions size="small" column={1} bordered>
    <Descriptions.Item label="来源草稿">{draftName(session)}</Descriptions.Item>
    <Descriptions.Item label="模式">{modeLabel(session)}</Descriptions.Item>
    <Descriptions.Item label="PR">{snapshotLabel(session, 'PR')}</Descriptions.Item>
    <Descriptions.Item label="WS">{session.input_bundle.ws_version_id ? snapshotLabel(session, 'WS') : 'NOT_EVALUATED'}</Descriptions.Item>
    <Descriptions.Item label="Factory">{snapshotLabel(session, 'FACTORY')}</Descriptions.Item>
    <Descriptions.Item label="Calendar">{snapshotLabel(session, 'CALENDAR')}</Descriptions.Item>
    <Descriptions.Item label="Initial">{snapshotLabel(session, 'INITIAL_STATE')}</Descriptions.Item>
    <Descriptions.Item label="WIP">{snapshotLabel(session, 'WIP_POLICY')}</Descriptions.Item>
    <Descriptions.Item label="Actual">{session.input_bundle.actual_revision_id ? snapshotLabel(session, 'ACTUAL') : 'NOT_EVALUATED'}</Descriptions.Item>
    <Descriptions.Item label="父 Formal">{session.parent_formal_pp_id ? '已按原候选冻结绑定' : 'NOT_EVALUATED'}</Descriptions.Item>
  </Descriptions>
}

function AbandonedSessionCandidates({
  session,
  openSessions,
}: {
  session: V6Session
  openSessions: V6Session[]
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const workbench = useQuery({
    queryKey: ['v6', 'abandoned-workbench', session.session_id],
    queryFn: () => v6Api.workbench(session.session_id),
    retry: false,
  })
  const recovery = useMutation({
    mutationFn: async (candidateId: string) => {
      const result = await v6Api.recoverAbandonedDraft(session.session_id, candidateId)
      if (result.outcome !== 'DRAFT_SESSION_RECOVERED' || !result.session_id) {
        throw new Error(result.message || '废弃草稿恢复失败')
      }
      return result
    },
    onSuccess: async (result) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['v6', 'sessions'] }),
        queryClient.invalidateQueries({ queryKey: ['v6', 'workbench'] }),
        queryClient.invalidateQueries({ queryKey: ['v6', 'abandoned-workbench'] }),
      ])
      message.success('已恢复为新的开放排产')
      navigate(`/v6/session/${encodeURIComponent(result.session_id!)}`)
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  if (workbench.isLoading) return <PageState kind="loading" rows={3} />
  if (workbench.isError) return <Alert type="error" showIcon message="候选详情或冻结版本不可用" description="原 Session 审计记录仍保留，但当前无法预览或恢复其中的 Candidate。" />
  const rows = workbench.data?.candidate_history || []

  const confirmRecovery = (row: V6CandidateHistoryItem) => {
    Modal.confirm({
      title: `恢复 Draft #${row.candidate_revision} 为新排产？`,
      width: 620,
      content: <Space direction="vertical" size={12} style={{ width: '100%', marginTop: 12 }}>
        <Alert
          type="warning"
          showIcon
          message="严格使用原候选的冻结版本"
          description="系统不会替换为当前 ACTIVE 版本；恢复时会重新执行当前 Preflight 和计划校验。原废弃 Session 不会改变。"
        />
        <RecoveryBindings session={session} />
      </Space>,
      okText: '创建新的开放排产',
      cancelText: '取消',
      onOk: () => recovery.mutateAsync(row.candidate_id),
    })
  }

  return <Space direction="vertical" size={14} style={{ width: '100%' }}>
    <Space wrap>
      <Tag>{modeLabel(session)}</Tag>
      <Tag color="blue">{planningYear(session)}</Tag>
      <Typography.Text type="secondary">放弃时间：{displayDate(session.closed_at)}</Typography.Text>
      <Button
        size="small"
        icon={<InfoCircleOutlined />}
        onClick={() => Modal.info({
          title: '草稿技术身份',
          width: 640,
          content: <Descriptions size="small" column={1} style={{ marginTop: 12 }}>
            <Descriptions.Item label="Session ID"><Typography.Text copyable code>{session.session_id}</Typography.Text></Descriptions.Item>
            <Descriptions.Item label="当前 Candidate ID"><Typography.Text copyable code>{session.current_candidate_id || '—'}</Typography.Text></Descriptions.Item>
          </Descriptions>,
        })}
      >技术详情</Button>
    </Space>
    <Table<V6CandidateHistoryItem>
      rowKey="candidate_id"
      size="small"
      pagination={false}
      scroll={{ x: 760 }}
      dataSource={rows}
      columns={[
        {
          title: '候选',
          render: (_, row) => <Space wrap><strong>Draft #{row.candidate_revision}</strong>{row.is_current && <Tag color="processing">放弃时当前 Draft</Tag>}</Space>,
        },
        { title: '生成原因', dataIndex: 'generation_reason', width: 180 },
        { title: '验证', dataIndex: 'validation_status', width: 100, render: validationTag },
        { title: '硬错误', width: 90, align: 'right', render: (_, row) => row.hard_error_codes.length },
        { title: '创建时间', dataIndex: 'created_at', width: 180, render: displayDate },
        {
          title: '操作',
          width: 220,
          fixed: 'right',
          render: (_, row) => <Space>
            <Button size="small" icon={<EyeOutlined />} onClick={() => navigate(`/v6/session/${encodeURIComponent(session.session_id)}?candidate=${encodeURIComponent(row.candidate_id)}`)}>查看</Button>
            <Button
              size="small"
              type="primary"
              icon={<BranchesOutlined />}
              disabled={openSessions.length > 0}
              loading={recovery.isPending}
              onClick={() => confirmRecovery(row)}
            >恢复</Button>
          </Space>,
        },
      ]}
    />
  </Space>
}

export function AbandonedDraftLibrary({ openSessions }: { openSessions: V6Session[] }) {
  const navigate = useNavigate()
  const sessions = useQuery({
    queryKey: ['v6', 'sessions', 'ABANDONED'],
    queryFn: () => v6Api.sessions('ABANDONED'),
    staleTime: 10_000,
    retry: false,
  })

  if (sessions.isLoading) return <PageState kind="loading" rows={5} />
  if (sessions.isError) return <PageState kind="system-error" error={sessions.error} onRetry={() => void sessions.refetch()} />
  const rows = [...(sessions.data || [])]
    .filter((session) => Boolean(session.current_candidate_id))
    .sort((left, right) => String(right.closed_at || '').localeCompare(String(left.closed_at || '')))
  if (!rows.length) return <Empty description="当前没有可恢复的废弃草稿" />

  return <Space direction="vertical" size={14} style={{ width: '100%' }}>
    {openSessions.length > 0 && <Alert
      type="warning"
      showIcon
      message="已有进行中的排产，暂不能恢复其他草稿"
      description="系统不会自动放弃或覆盖当前工作。请先继续、保存或主动放弃当前排产。"
      action={<Button type="primary" icon={<PlayCircleOutlined />} onClick={() => navigate(`/v6/session/${encodeURIComponent(openSessions[0].session_id)}`)}>继续当前排产</Button>}
    />}
    <Alert
      type="info"
      showIcon
      message="废弃草稿只读保留"
      description="恢复会严格复制所选候选的冻结输入和原计划，创建新的 OPEN Session；原 Session 和 Candidate 永远保持 ABANDONED 审计记录。"
    />
    <Collapse
      items={rows.map((session) => ({
        key: session.session_id,
        label: <Space wrap><strong>{draftName(session)}</strong><Tag>{modeLabel(session)}</Tag><Tag>{planningYear(session)}</Tag><Typography.Text type="secondary">{displayDate(session.closed_at)}</Typography.Text></Space>,
        children: <AbandonedSessionCandidates session={session} openSessions={openSessions} />,
      }))}
    />
  </Space>
}
