import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Card, Input, message, Space, Tag } from 'antd'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from '../../../api/planning'
import { PageHeader } from '../../../components/PageHeader'
import { PageState } from '../../../components/PageState'
import { StatusTag } from '../../../components/StatusTag'
import { YearCalendar } from '../../../components/YearCalendar'
import {
  CALENDAR_YEAR_MAX,
  CALENDAR_YEAR_MIN,
  hasCalendarBaseline,
} from '../../../utils/holidays'
import {
  assertCompleteCalendarYear,
  calendarDraftForYear,
  calendarYears,
  defaultCalendarYear,
  sameCalendarDays,
  setCalendarYearDraft,
  type CalendarDraftDay,
  type CalendarDraftsByYear,
} from '../../../utils/calendarDraft'
import { VersionEditorFooter } from './VersionEditorFooter'

export function CalendarEditorPage() {
  const queryClient = useQueryClient()
  const listQuery = useQuery({
    queryKey: ['calendar-versions'],
    queryFn: () => api.calendarVersions(),
  })
  const active = (listQuery.data || []).find((v: any) => v.status === 'ACTIVE')
  const detailQuery = useQuery({
    queryKey: ['calendar-version-detail', active?.calendar_version_id],
    queryFn: () => api.calendarVersionDetail(active!.calendar_version_id),
    enabled: Boolean(active),
  })
  const currentYear = Math.min(
    CALENDAR_YEAR_MAX,
    Math.max(CALENDAR_YEAR_MIN, new Date().getFullYear()),
  )
  const [selectedYear, setSelectedYear] = useState(currentYear)
  const [drafts, setDrafts] = useState<CalendarDraftsByYear>({})
  const [displayName, setDisplayName] = useState(`${currentYear} 企业日历`)

  const savedDays = useMemo<CalendarDraftDay[]>(
    () =>
      (detailQuery.data?.days || []).map((d: any) => ({
        date: d.date,
        is_working_capable: d.is_working_capable ?? true,
        reason: d.reason ?? '',
      })),
    [detailQuery.data],
  )
  const activeYears = useMemo(() => calendarYears(savedDays), [savedDays])
  const activeYear = (
    activeYears.length === 1
    && activeYears[0] >= CALENDAR_YEAR_MIN
    && activeYears[0] <= CALENDAR_YEAR_MAX
  )
    ? activeYears[0]
    : currentYear
  const savedSelectedYear = useMemo(
    () => calendarDraftForYear(savedDays, selectedYear),
    [savedDays, selectedYear],
  )
  const selectedDraft = drafts[selectedYear] || savedSelectedYear
  const selectedIsActive = activeYears.length === 1 && activeYears[0] === selectedYear
  const dirty = !selectedIsActive
    || !sameCalendarDays(selectedDraft, savedSelectedYear)
    || displayName.trim() !== active?.display_name
  const overrides = useMemo(
    () => [...savedDays, ...Object.values(drafts).flat()],
    [drafts, savedDays],
  )

  useEffect(() => {
    setSelectedYear(activeYear)
    setDrafts({})
    if (active) setDisplayName(active.display_name)
  }, [active?.calendar_version_id, activeYear])

  const saveMutation = useMutation({
    mutationFn: () => {
      assertCompleteCalendarYear(selectedDraft, selectedYear)
      return api.createCalendarVersion({
        display_name: displayName.trim(),
        days: selectedDraft,
        supersedes_calendar_version_id: active?.calendar_version_id ?? undefined,
      })
    },
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        message.success(`已创建 ${selectedYear} Calendar 版本`)
        queryClient.invalidateQueries({ queryKey: ['calendar-versions'] })
      } else {
        message.error(`保存失败: ${result.outcome}`)
      }
    },
    onError: () => message.error('保存失败'),
  })

  const createDefaultMutation = useMutation({
    mutationFn: () => api.createCalendarVersion({
      display_name: displayName.trim(),
      days: defaultCalendarYear(currentYear),
    }),
    onSuccess: (result) => {
      if (result.outcome === 'CREATED') {
        message.success(`已创建 ${currentYear} 企业日历`)
        queryClient.invalidateQueries({ queryKey: ['calendar-versions'] })
      } else {
        message.error(`创建失败: ${result.outcome}`)
      }
    },
    onError: (error) => message.error(error instanceof Error ? error.message : '创建失败'),
  })

  if (listQuery.isLoading || detailQuery.isLoading) return <PageState kind="loading" rows={6} />
  if (listQuery.error || detailQuery.error)
    return <PageState kind="system-error" error={listQuery.error || detailQuery.error} onRetry={() => window.location.reload()} />
  if (!active) {
    const canCreate = hasCalendarBaseline(currentYear)
    return (
      <div>
        <PageHeader
          title="企业日历"
          subtitle="基于权威法定节假日创建并版本化"
          actions={<Input aria-label="Calendar 短名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="输入短名称" style={{ width: 220 }} />}
        />
        <PageState
          kind="business-blocked"
          title="尚未配置企业日历"
          reasons={[
            canCreate
              ? `${currentYear} 年日历基线已维护，可直接创建后逐日调整`
              : `${currentYear} 年企业日历基线待维护`,
          ]}
          action={canCreate ? (
            <Button
              type="primary"
              loading={createDefaultMutation.isPending}
              disabled={!displayName.trim()}
              onClick={() => createDefaultMutation.mutate()}
            >
              创建 {currentYear} 企业日历
            </Button>
          ) : undefined}
        />
      </div>
    )
  }

  return (
    <div className="calendar-editor-page">
      <PageHeader
        title="企业日历"
        subtitle="全年工作日/休息日（点击日期切换；双班覆盖日请在理由中注明）"
        actions={(
          <Space>
            <Input aria-label="Calendar 短名称" value={displayName} onChange={(event) => setDisplayName(event.target.value)} placeholder="输入短名称" style={{ width: 220 }} />
            <Tag color={activeYears.length === 1 ? 'blue' : 'error'}>
              ACTIVE Calendar：{activeYears.length === 1 ? activeYears[0] : `跨年 ${activeYears.join(' / ')}`}
            </Tag>
            <StatusTag value={active.status} />
          </Space>
        )}
      />
      <Card size="small">
        {activeYears.length !== 1 && (
          <Alert
            type="error"
            showIcon
            style={{ marginBottom: 12 }}
            message="当前活动 Calendar 跨越多个年份，不能用于年度排产"
            description="请选择一个年份并保存为新的单年度 Calendar，或在 Portable Launcher 中重置 Demo。"
          />
        )}
        {activeYears.length === 1 && selectedYear !== activeYear && (
          <Alert
            type="info"
            showIcon
            style={{ marginBottom: 12 }}
            message={`当前显示 ${selectedYear} 未保存年度模板`}
            description={`当前活动 Calendar 为 ${activeYear}；保存后 ${selectedYear} 将成为唯一 ACTIVE Calendar。`}
          />
        )}
        <YearCalendar
          key={active.calendar_version_id}
          year={activeYear}
          editable
          overrides={overrides}
          onChange={(year, result) => {
            setSelectedYear(year)
            setDrafts((current) => setCalendarYearDraft(current, year, result))
          }}
        />
        <VersionEditorFooter
          dirty={dirty}
          saving={saveMutation.isPending}
          onCancel={() => window.history.back()}
          onSave={() => displayName.trim() ? saveMutation.mutate() : message.error('请输入非空 Calendar 短名称')}
          note={`当前活动 Calendar：${activeYear}`}
        />
      </Card>
    </div>
  )
}
