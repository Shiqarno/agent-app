import type { ReactNode } from 'react'
import type { CurrentUser } from './api/auth'
import { Link, useRouter } from './router'

const ADULT_NAV_ITEMS: { to: string; label: string }[] = [
  { to: '/dashboard', label: 'Dashboard' },
  { to: '/tasks', label: 'Tasks' },
  { to: '/users', label: 'Users' },
  { to: '/rewards', label: 'Rewards' },
  { to: '/points', label: 'Points' },
]

// Children get Tasks (their home) plus Rewards/Points -- no Dashboard or
// Users management (out of scope; see App.tsx).
const CHILD_NAV_ITEMS: { to: string; label: string }[] = [
  { to: '/tasks', label: 'Tasks' },
  { to: '/rewards', label: 'Rewards' },
  { to: '/points', label: 'Points' },
]

function AppShell({
  user,
  onLogout,
  children,
}: {
  user: CurrentUser
  onLogout: () => void
  children: ReactNode
}) {
  const { path } = useRouter()
  const navItems = user.role === 'adult' ? ADULT_NAV_ITEMS : CHILD_NAV_ITEMS

  return (
    <div>
      <header>
        <nav className="app-nav" aria-label="Primary">
          <ul>
            {navItems.map((item) => (
              <li key={item.to}>
                <Link to={item.to} aria-current={path === item.to ? 'page' : undefined}>
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
        <p>
          Signed in as {user.name} ({user.role})
          <button onClick={onLogout}>Log out</button>
        </p>
      </header>
      <main className="app-main">{children}</main>
    </div>
  )
}

export default AppShell
