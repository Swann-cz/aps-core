import type { ReactNode } from 'react'

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: string; actions?: ReactNode }) {
  return <div className="page-heading">
    <div>
      <h1>{title}{subtitle && <span>{subtitle}</span>}</h1>
    </div>
    {actions && <div className="page-heading-actions">{actions}</div>}
  </div>
}
