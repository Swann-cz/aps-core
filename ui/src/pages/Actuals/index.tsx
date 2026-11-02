import { useState } from 'react'
import { Button, Card, Space, Tag, Table } from 'antd'
import { FileExcelOutlined, ImportOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import { PageHeader } from '../../components/PageHeader'
import { PageState } from '../../components/PageState'
import { ActualImportDrawer } from './ActualImportDrawer'
import { AnnualActualImportDrawer } from './AnnualActualImportDrawer'

export function Actuals() {
  const [importOpen, setImportOpen] = useState(false)
  const [annualImportOpen, setAnnualImportOpen] = useState(false)
  const { data: revisions = [], isLoading, error } = useQuery({
    queryKey: ['actual-revisions'],
    queryFn: () => api.actualRevisions(),
  })

  if (isLoading) return <PageState kind="loading" rows={6} />
  if (error) return <PageState kind="system-error" error={error} onRetry={() => window.location.reload()} />

  const latest = revisions.length ? revisions[revisions.length - 1] : null

  return (
    <div>
      <PageHeader
        title="实际数据"
        subtitle="Actual 是事实：保存修订不触发自动重排；重排由计划员显式发起"
        actions={
          <Space>
            <Button data-testid="actual-v2-import-open" icon={<FileExcelOutlined />} onClick={() => setAnnualImportOpen(true)}>
              导入全年 Actual Filling
            </Button>
            <Button type="primary" icon={<ImportOutlined />} onClick={() => setImportOpen(true)}>
              导入旧版 Actual
            </Button>
          </Space>
        }
      />
      <Card size="small" title="覆盖摘要" style={{ marginBottom: 16 }}>
        {latest ? (
          <Space wrap>
            <Tag>最新记录：{latest.recorded_at ? latest.recorded_at.slice(0, 19).replace('T', ' ') : '—'}</Tag>
            <Tag>生效日：{latest.effective_date || '—'}</Tag>
            <Tag>修订数：{revisions.length}</Tag>
          </Space>
        ) : (
          <span className="muted">尚无 ActualRevision。</span>
        )}
      </Card>
      <Card size="small" title="实际数据修订">
        <Table
          size="small" bordered rowKey="actual_revision_id"
          dataSource={revisions}
          pagination={{ pageSize: 10 }}
          columns={[
            { title: 'Revision ID', dataIndex: 'actual_revision_id', render: (v: string) => <code>{v.slice(0, 8)}…</code> },
            { title: 'Schema', dataIndex: 'schema_version', render: (v: number | undefined) => <Tag color={v === 2 ? 'blue' : 'default'}>V{v || 1}</Tag> },
            { title: '生效日期', dataIndex: 'effective_date', render: (v: string) => v || '—' },
            { title: '来源 Formal', dataIndex: 'source_formal_pp_id', render: (v: string | null | undefined) => (v ? <code>{v.slice(0, 8)}…</code> : '—') },
            { title: '记录时间', dataIndex: 'recorded_at', render: (v: string) => (v ? v.slice(0, 19).replace('T', ' ') : '—') },
            { title: '替代修订', dataIndex: 'supersedes_revision_id', render: (v: string | null) => (v ? <code>{v.slice(0, 8)}…</code> : <Tag>初始</Tag>) },
          ]}
        />
      </Card>
      <ActualImportDrawer
        open={importOpen}
        onClose={() => setImportOpen(false)}
        onSaved={() => undefined}
      />
      <AnnualActualImportDrawer
        open={annualImportOpen}
        onClose={() => setAnnualImportOpen(false)}
        revisions={revisions}
      />
    </div>
  )
}
