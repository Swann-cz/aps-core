import { useEffect, useMemo, useState } from 'react'
import { Alert, Button, Modal, Select, Space, Typography, message } from 'antd'
import { DownloadOutlined } from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { api } from '../../api/planning'
import type { CalendarVersion, FactoryModelVersion } from '../../types/api'

function downloadFile(file: { blob: Blob; filename: string }) {
  const url = URL.createObjectURL(file.blob)
  const link = document.createElement('a')
  link.href = url
  link.download = file.filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
}

function createdAtLabel(value?: string | null) {
  if (!value) return ''
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return ''
  return parsed.toLocaleString('zh-CN', { hour12: false })
}

function calendarLabel(calendar: CalendarVersion) {
  const prefix = calendar.calendar_year ? `${calendar.calendar_year} 年` : '年份异常'
  const reason = calendar.covers_full_year ? '' : ' · 不完整自然年，不可用'
  const created = createdAtLabel(calendar.created_at)
  const createdSuffix = created ? ` · ${created}` : ''
  return `${prefix} · ${calendar.display_name} · ${calendar.status}${createdSuffix}${reason}`
}

function factoryLabel(factory: FactoryModelVersion) {
  const typeclasses = factory.typeclass_ids || []
  const typeclassLabel = typeclasses.length ? typeclasses.join('、') : '无车型，不可用'
  const created = createdAtLabel(factory.created_at)
  const createdSuffix = created ? ` · ${created}` : ''
  return `${factory.display_name} · ${factory.status} · 车型 ${typeclassLabel}${createdSuffix}`
}

export function SalesTemplateDownloadButton() {
  const [open, setOpen] = useState(false)
  const [calendarId, setCalendarId] = useState<string>()
  const [factoryId, setFactoryId] = useState<string>()
  const [downloading, setDownloading] = useState(false)

  const calendarsQuery = useQuery({
    queryKey: ['calendar-versions'],
    queryFn: () => api.calendarVersions(),
    enabled: open,
    staleTime: 30_000,
  })
  const factoriesQuery = useQuery({
    queryKey: ['factory-model-versions'],
    queryFn: () => api.factoryModelVersions(),
    enabled: open,
    staleTime: 30_000,
  })

  const calendars = useMemo(
    () => [...(calendarsQuery.data || [])].sort(
      (left, right) => (
        (left.calendar_year || 0) - (right.calendar_year || 0)
        || left.display_name.localeCompare(right.display_name, 'zh-CN')
      ),
    ),
    [calendarsQuery.data],
  )
  const factories = factoriesQuery.data || []

  useEffect(() => {
    if (!open || factoryId || !factories.length) return
    const active = factories.find(
      (factory) => factory.status === 'ACTIVE' && (factory.typeclass_ids || []).length > 0,
    )
    if (active) setFactoryId(active.factory_model_version_id)
  }, [factories, factoryId, open])

  const selectedCalendar = calendars.find(
    (calendar) => calendar.calendar_version_id === calendarId,
  )
  const selectedFactory = factories.find(
    (factory) => factory.factory_model_version_id === factoryId,
  )
  const typeclasses = selectedFactory?.typeclass_ids || []
  const canDownload = Boolean(
    selectedCalendar?.covers_full_year
    && selectedCalendar.calendar_year
    && typeclasses.length
    && !calendarsQuery.error
    && !factoriesQuery.error,
  )

  const openDialog = () => {
    setCalendarId(undefined)
    setFactoryId(undefined)
    setOpen(true)
  }

  const downloadTemplate = async () => {
    if (!calendarId || !factoryId || !selectedCalendar?.calendar_year) return
    setDownloading(true)
    try {
      downloadFile(await api.downloadSalesPlanTemplate(calendarId, factoryId))
      message.success(
        `已生成 ${selectedCalendar.calendar_year} 年、${typeclasses.length} 个车型、`
        + `${typeclasses.length * 12} 行模板`,
      )
      setOpen(false)
    } catch (error) {
      message.error(error instanceof Error ? error.message : '模板下载失败')
    } finally {
      setDownloading(false)
    }
  }

  const queryError = calendarsQuery.error || factoriesQuery.error

  return (
    <>
      <Button icon={<DownloadOutlined />} onClick={openDialog}>下载模板</Button>
      <Modal
        title="生成销售计划模板"
        open={open}
        okText="下载"
        cancelText="取消"
        confirmLoading={downloading}
        okButtonProps={{ disabled: !canDownload || downloading }}
        cancelButtonProps={{ disabled: downloading }}
        closable={!downloading}
        maskClosable={!downloading}
        onOk={() => void downloadTemplate()}
        onCancel={() => setOpen(false)}
      >
        <Space direction="vertical" size={16} style={{ width: '100%' }}>
          <Alert
            type="info"
            showIcon
            message="模板年份来自 Calendar，车型来自 Factory；PR、WS 将保持空白。"
          />
          {queryError && (
            <Alert
              type="error"
              showIcon
              message="版本列表加载失败"
              description={queryError instanceof Error ? queryError.message : '请关闭弹窗后重试'}
            />
          )}
          <div>
            <Typography.Text strong>Calendar</Typography.Text>
            <Select
              aria-label="模板 Calendar"
              style={{ width: '100%', marginTop: 6 }}
              placeholder="请选择完整自然年的 Calendar"
              loading={calendarsQuery.isLoading}
              value={calendarId}
              onChange={setCalendarId}
              options={calendars.map((calendar) => ({
                value: calendar.calendar_version_id,
                label: calendarLabel(calendar),
                disabled: !calendar.covers_full_year || !calendar.calendar_year,
              }))}
            />
          </div>
          <div>
            <Typography.Text strong>Factory</Typography.Text>
            <Select
              aria-label="模板 Factory"
              style={{ width: '100%', marginTop: 6 }}
              placeholder="请选择包含车型的 Factory"
              loading={factoriesQuery.isLoading}
              value={factoryId}
              onChange={setFactoryId}
              options={factories.map((factory) => ({
                value: factory.factory_model_version_id,
                label: factoryLabel(factory),
                disabled: !(factory.typeclass_ids || []).length,
              }))}
            />
          </div>
          {selectedCalendar?.calendar_year && typeclasses.length > 0 && (
            <Alert
              type="success"
              showIcon
              message={`${selectedCalendar.calendar_year} 年｜车型 ${typeclasses.join('、')}`
                + `｜共 ${typeclasses.length * 12} 行`}
            />
          )}
        </Space>
      </Modal>
    </>
  )
}
