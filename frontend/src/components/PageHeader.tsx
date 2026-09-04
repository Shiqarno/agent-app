import type { ReactNode } from 'react'

function PageHeader({
  title,
  action,
  children,
}: {
  title: string
  action?: ReactNode
  children?: ReactNode
}) {
  return (
    <div className="page-header">
      <div className="page-header-row">
        <h1>{title}</h1>
        {action}
      </div>
      {children && <div className="page-header-body">{children}</div>}
    </div>
  )
}

export default PageHeader
