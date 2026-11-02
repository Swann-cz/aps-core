import { CalendarOutlined, ControlOutlined, TableOutlined, PlusOutlined, FileDoneOutlined } from '@ant-design/icons'
export const primaryNav = [
  { key: '/wizard', label: '排产向导', icon: <PlusOutlined /> },
  { key: '/annual-overview', label: '年度总览', icon: <CalendarOutlined /> },
  { key: '/monthly-filling', label: '月度明细', icon: <TableOutlined /> },
  { key: '/planning-conditions', label: '排产条件', icon: <ControlOutlined /> },
  { key: '/formal', label: '正式版本', icon: <FileDoneOutlined /> },
]
