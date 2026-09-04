import type { ButtonHTMLAttributes } from 'react'

function Button({
  variant = 'primary',
  loading = false,
  disabled,
  className,
  children,
  ...rest
}: {
  variant?: 'primary' | 'secondary' | 'destructive' | 'ghost'
  loading?: boolean
} & ButtonHTMLAttributes<HTMLButtonElement>) {
  const classes = ['btn', `btn-${variant}`, loading ? 'btn-loading' : '', className]
    .filter(Boolean)
    .join(' ')

  return (
    <button
      className={classes}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {children}
    </button>
  )
}

export default Button
