import type { ReactNode } from 'react'

function Badge({
  tone = 'neutral',
  children,
}: {
  tone?: 'neutral' | 'success' | 'warning' | 'error' | 'info'
  children: ReactNode
}) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export default Badge
