import { type ComponentType, type FormEvent, useEffect, useState } from 'react'
import { activate, login, logout, me, type CurrentUser } from './api/auth'
import AppShell from './AppShell'
import DashboardPage from './pages/DashboardPage'
import EditRewardPage from './pages/EditRewardPage'
import NewRewardPage from './pages/NewRewardPage'
import NewTaskPage from './pages/NewTaskPage'
import NewUserPage from './pages/NewUserPage'
import PointsPage from './pages/PointsPage'
import RewardsPage from './pages/RewardsPage'
import TasksPage from './pages/TasksPage'
import UsersPage from './pages/UsersPage'
import { RouterProvider, useRouter } from './router'

type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous' }
  | { phase: 'authenticated'; user: CurrentUser }

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function LoginForm({ onLogin }: { onLogin: (user: CurrentUser) => void }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const user = await login(email, password)
      onLogin(user)
    } catch (err) {
      setError(errorMessage(err, 'Login failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Sign in</h1>
      <div>
        <label htmlFor="email">Email</label>
        <input
          id="email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor="password">Password</label>
        <input
          id="password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting}>
        Sign in
      </button>
    </form>
  )
}

function ActivationForm({
  token,
  onActivated,
}: {
  token: string
  onActivated: (user: CurrentUser) => void
}) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setSubmitting(true)

    try {
      const user = await activate(token, email, password)
      onActivated(user)
    } catch (err) {
      setError(errorMessage(err, 'Activation failed.'))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <h1>Activate your account</h1>
      <div>
        <label htmlFor="activation-email">Email</label>
        <input
          id="activation-email"
          type="email"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
        />
      </div>
      <div>
        <label htmlFor="activation-password">Password</label>
        <input
          id="activation-password"
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </div>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={submitting}>
        Activate
      </button>
    </form>
  )
}

// Adult-only routes. Static paths only -- no nested/dynamic segments are
// needed, so a plain lookup table is enough (see router.tsx).
const ADULT_ROUTES: Record<string, ComponentType> = {
  '/': DashboardPage,
  '/dashboard': DashboardPage,
  '/tasks': TasksPage,
  '/tasks/new': NewTaskPage,
  '/users': UsersPage,
  '/users/new': NewUserPage,
  '/rewards': RewardsPage,
  '/rewards/new': NewRewardPage,
  '/points': PointsPage,
}

// The only route with a dynamic segment. A single regex check is enough --
// see router.tsx for why a full route-matching library isn't warranted here.
const REWARD_EDIT_PATH = /^\/rewards\/[^/]+\/edit$/

function resolveAdultPage(path: string): ComponentType {
  if (ADULT_ROUTES[path]) return ADULT_ROUTES[path]
  if (REWARD_EDIT_PATH.test(path)) return EditRewardPage
  return DashboardPage
}

// Children get the minimum Rewards/Points access this issue requires (view
// balance/history/catalog, redeem) -- everything else, including Reward
// management and any Adult-only path, falls back to /rewards. A full Child
// shell/Dashboard remains out of scope; this reuses the same RewardsPage
// and PointsPage Adults use rather than creating separate Child pages.
const CHILD_ROUTES: Record<string, ComponentType> = {
  '/rewards': RewardsPage,
  '/points': PointsPage,
}

function resolveChildPage(path: string): ComponentType {
  return CHILD_ROUTES[path] ?? RewardsPage
}

function AuthenticatedApp({ user, onLogout }: { user: CurrentUser; onLogout: () => void }) {
  const { path } = useRouter()
  const Page = user.role === 'adult' ? resolveAdultPage(path) : resolveChildPage(path)

  return (
    <AppShell user={user} onLogout={onLogout}>
      <Page />
    </AppShell>
  )
}

function App() {
  const [auth, setAuth] = useState<AuthState>({ phase: 'loading' })
  // The activation link (POST /api/users creates this token server-side, out
  // of band -- Issue #10) lives at /activate?activation_token=... . It is
  // read once and never persisted client-side (no localStorage), matching
  // the same "never store a raw token" discipline as the session cookie.
  const [activationToken] = useState(() =>
    window.location.pathname === '/activate'
      ? new URLSearchParams(window.location.search).get('activation_token')
      : null,
  )

  useEffect(() => {
    let cancelled = false

    me()
      .then((user) => {
        if (!cancelled) {
          setAuth({ phase: 'authenticated', user })
        }
      })
      .catch(() => {
        if (!cancelled) {
          setAuth({ phase: 'anonymous' })
        }
      })

    return () => {
      cancelled = true
    }
  }, [])

  async function handleLogout() {
    try {
      await logout()
    } finally {
      setAuth({ phase: 'anonymous' })
    }
  }

  function handleAuthenticated(user: CurrentUser) {
    // Dashboard is the landing page after a successful Adult login.
    if (user.role === 'adult' && window.location.pathname !== '/dashboard') {
      window.history.pushState({}, '', '/dashboard')
    }
    setAuth({ phase: 'authenticated', user })
  }

  if (auth.phase === 'loading') {
    return <p>Loading...</p>
  }

  if (auth.phase === 'anonymous') {
    if (activationToken) {
      return <ActivationForm token={activationToken} onActivated={handleAuthenticated} />
    }
    return <LoginForm onLogin={handleAuthenticated} />
  }

  return (
    <RouterProvider>
      <AuthenticatedApp user={auth.user} onLogout={handleLogout} />
    </RouterProvider>
  )
}

export default App
