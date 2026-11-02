import { BranchesOutlined, CloseCircleOutlined, PlayCircleOutlined, PlusCircleOutlined } from '@ant-design/icons'
import { Alert, Button, Card, Col, Modal, Row, Space, Tabs, Tag, Typography, message } from 'antd'
import { useMutation } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { useV6Planning } from '../../app/V6PlanningContext'
import { v6Api } from '../../api/v6'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { AbandonedDraftLibrary } from './AbandonedDraftLibrary'

export function V6StartPlanning() {
  const navigate = useNavigate()
  const state = useV6Planning()
  const abandon = useMutation({
    mutationFn: async () => {
      if (!state.activeSession) throw new Error('当前没有开放 Session')
      return v6Api.abandonSession(state.activeSession.session_id, state.activeSession.planning_revision)
    },
    onSuccess: async (result) => {
      if (result.outcome !== 'SESSION_ABANDONED') throw new Error(result.message)
      message.success('当前排产已放弃，可在废弃草稿库中只读查看或恢复')
      await state.refresh()
    },
    onError: (error) => message.error(error instanceof Error ? error.message : String(error)),
  })

  if (state.loading) return <PageState kind="loading" rows={5} />
  if (state.error) return <PageState kind="system-error" error={state.error} onRetry={() => void state.refresh()} />

  const session = state.activeSession
  const currentContent = state.multipleOpenSessions
    ? <PageState
        kind="business-blocked"
        title="检测到多个开放 V6.1.4 Session"
        reasons={state.openSessions.map((item) => `${item.generation_mode} · ${item.session_id} · rev.${item.planning_revision}`)}
      />
    : session
      ? <Card className="v6-resume-card">
          <div className="v6-resume-head">
            <div>
              <Space wrap>
                <Tag color="processing">进行中</Tag>
                <Tag>{session.generation_mode === 'INITIAL_FROM_ZERO' ? '初始排产' : 'Rolling'}</Tag>
              </Space>
              <Typography.Title level={3}>{session.work_note || (session.generation_mode === 'INITIAL_FROM_ZERO' ? 'V6.1.4 初始排产' : 'V6.1.4 Rolling')}</Typography.Title>
              <Typography.Text type="secondary">Session {session.session_id} · rev.{session.planning_revision}</Typography.Text>
            </div>
            <div className="v6-resume-revision">{state.workbench?.current_candidate ? `Draft #${state.workbench.current_candidate.candidate_revision}` : '待生成候选'}</div>
          </div>
          <div className="v6-resume-grid">
            <div><span>PR</span><strong>{session.input_bundle.business_id_snapshots.find((item) => item.kind === 'PR')?.business_id || session.input_bundle.pr_version_id}</strong></div>
            <div><span>WS</span><strong>{session.input_bundle.ws_version_id ? session.input_bundle.business_id_snapshots.find((item) => item.kind === 'WS')?.business_id : 'NOT_EVALUATED'}</strong></div>
            <div><span>条件</span><strong>{session.input_bundle.condition_snapshot.items.length} 项</strong></div>
            <div><span>问题 / 警告</span><strong>{(state.workbench?.current_candidate?.hard_error_codes.length || 0) + (state.workbench?.current_candidate?.warning_codes.length || 0)} 项</strong></div>
          </div>
          <Alert
            type="info"
            showIcon
            message={state.workbench?.current_candidate ? 'DraftCandidate 已自动保存' : '开放 Session 已自动保存'}
            description="关闭或重新打开浏览器不会删除当前进度。放弃后原草稿保持只读，可从废弃草稿库恢复为新的排产。"
            style={{ marginTop: 16 }}
          />
          <Space style={{ marginTop: 20 }}>
            <Button type="primary" size="large" icon={<PlayCircleOutlined />} onClick={() => navigate(`/v6/session/${session.session_id}`)}>继续当前排产</Button>
            <Button
              danger
              icon={<CloseCircleOutlined />}
              loading={abandon.isPending}
              onClick={() => Modal.confirm({
                title: '放弃本次排产？',
                content: 'Session 将关闭且不能原地继续；DraftCandidate 不会进入正式 PP 库，但会保留在废弃草稿库，可只读查看并恢复为新的排产。',
                okText: '确认放弃',
                okButtonProps: { danger: true },
                cancelText: '取消',
                onOk: () => abandon.mutateAsync(),
              })}
            >放弃本次排产</Button>
          </Space>
        </Card>
      : <>
          <Alert type="info" showIcon message="当前没有进行中的 V6.1.4 排产" description="初始排产从完整输入开始；Rolling 必须选择一个正式父 PP。" style={{ marginBottom: 18 }} />
          <Row gutter={[18, 18]}>
            <Col xs={24} lg={12}>
              <Card className="v6-mode-card initial" hoverable onClick={() => navigate('/v6/initial')}>
                <div className="v6-mode-icon"><PlusCircleOutlined /></div>
                <Typography.Text className="v6-kicker">INITIAL_FROM_ZERO</Typography.Text>
                <Typography.Title level={3}>初始排产</Typography.Title>
                <Typography.Paragraph>明确选择 PR、可选 WS 与基础设置，不引用父正式 PP。</Typography.Paragraph>
                <Button type="primary">进入初始排产</Button>
              </Card>
            </Col>
            <Col xs={24} lg={12}>
              <Card className="v6-mode-card rolling" hoverable onClick={() => navigate('/v6/rolling')}>
                <div className="v6-mode-icon"><BranchesOutlined /></div>
                <Typography.Text className="v6-kicker">ROLLING_FROM_FORMAL_PP</Typography.Text>
                <Typography.Title level={3}>Rolling</Typography.Title>
                <Typography.Paragraph>从正式父 PP 继承输入，显式绑定 PR、Actual、Fix 月份和本轮变化。</Typography.Paragraph>
                <Button type="primary">进入 Rolling</Button>
              </Card>
            </Col>
          </Row>
        </>

  return <div className="page-container v6-start-page">
    <PageHeader title="开始排产" subtitle="继续当前工作、新建排产或从废弃草稿创建新的开放 Session" />
    <Tabs
      defaultActiveKey="current"
      items={[
        { key: 'current', label: '当前 / 新建排产', children: currentContent },
        { key: 'abandoned', label: '废弃草稿库', children: <AbandonedDraftLibrary openSessions={state.openSessions} /> },
      ]}
    />
  </div>
}
