import { AppstoreOutlined } from '@ant-design/icons'
import { Card, Empty } from 'antd'
import { PageHeader } from '../components/PageHeader'

export function ScopePlaceholder({ title }: { title: string }) {
  return <div className="page-container"><PageHeader title={title} subtitle="(本阶段未接入)" /><Card className="scope-notice"><Empty image={<AppstoreOutlined className="scope-icon" />} description={<><strong>本阶段只读范围为 F01 Annual Overview、F02 Monthly Filling、F03 Day Why、F06 PlanVersion。</strong><br />该入口不展示伪造的计划数据或后端能力。</>} /></Card></div>
}
