import { type ComponentType, useCallback, useEffect, useState } from 'react'
import { logout, me, type CurrentUser } from './api/auth'
import AppShell from './AppShell'
import ActivationPage from './pages/ActivationPage'
import DashboardPage from './pages/DashboardPage'
import EditRewardPage from './pages/EditRewardPage'
import EditTaskPage from './pages/EditTaskPage'
import NewRewardPage from './pages/NewRewardPage'
import NewTaskPage from './pages/NewTaskPage'
import NewUserPage from './pages/NewUserPage'
import PasswordLoginPage from './pages/PasswordLoginPage'
import PinSetupRequiredPage from './pages/PinSetupRequiredPage'
import PointsPage from './pages/PointsPage'
import ProfileLoginPage from './pages/ProfileLoginPage'
import ProfilePage from './pages/ProfilePage'
import RewardsPage from './pages/RewardsPage'
import TaskDetailsPage from './pages/TaskDetailsPage'
import TasksPage from './pages/TasksPage'
import UsersPage from './pages/UsersPage'
import { RouterProvider, useRouter } from './router'

type AuthState =
  | { phase: 'loading' }
  | { phase: 'anonymous' }
  | { phase: 'pin-setup-required'; user: CurrentUser }
  | { phase: 'authenticated'; user: CurrentUser }

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

// Routes with a dynamic segment. Plain regex checks are enough -- see
// router.tsx for why a full route-matching library isn't warranted here.
const REWARD_EDIT_PATH = /^\/rewards\/[^/]+\/edit$/
const TASK_EDIT_PATH = /^\/tasks\/[^/]+\/edit$/
// Deliberately excludes /tasks/new (an exact match in ADULT_ROUTES, checked
// first) and /tasks/:id/edit (a second path segment, which [^/]+$ rejects).
const TASK_DETAILS_PATH = /^\/tasks\/[^/]+$/

function resolveAdultPage(path: string): ComponentType {
  if (ADULT_ROUTES[path]) return ADULT_ROUTES[path]
  if (REWARD_EDIT_PATH.test(path)) return EditRewardPage
  if (TASK_EDIT_PATH.test(path)) return EditTaskPage
  if (TASK_DETAILS_PATH.test(path)) return TaskDetailsPage
  return DashboardPage
}

// Children get Tasks (their default/home route) -- including Task Details,
// since a Child is routinely the assignee a Task Details page's Start/Mark
// ready actions are for -- plus the Rewards/Points access from Issue #14.
// Everything else, including Reward/User management, Dashboard, Task
// creation, and Task editing (edit is creator-only, and a Child can never
// be a creator), falls back to /tasks. A full Child shell/Dashboard remains
// out of scope; this reuses the same TasksPage, TaskDetailsPage,
// RewardsPage, and PointsPage Adults use (each already role-aware
// internally) rather than creating separate Child pages.
const CHILD_ROUTES: Record<string, ComponentType> = {
  '/tasks': TasksPage,
  '/rewards': RewardsPage,
  '/points': PointsPage,
}

function resolveChildPage(path: string): ComponentType {
  if (CHILD_ROUTES[path]) return CHILD_ROUTES[path]
  // Unlike resolveAdultPage, there's no exact match for /tasks/new here to
  // short-circuit before the regex -- it's deliberately absent from
  // CHILD_ROUTES (Task creation is Adult-only) -- so it must be excluded
  // explicitly, or "new" would be treated as a task id.
  if (path !== '/tasks/new' && TASK_DETAILS_PATH.test(path)) return TaskDetailsPage
  return TasksPage
}

// /profile is available to both roles and, unlike every other route, needs
// props (the current user, and a way to hand a successful avatar change
// back up to `App`'s own auth state) that the generic <Page /> dispatch
// below has no mechanism to pass -- so it's special-cased ahead of that
// dispatch rather than added to ADULT_ROUTES/CHILD_ROUTES.
const PROFILE_PATH = '/profile'

function AuthenticatedApp({
  user,
  onLogout,
  onUserUpdated,
}: {
  user: CurrentUser
  onLogout: () => void
  onUserUpdated: (user: CurrentUser) => void
}) {
  const { path } = useRouter()

  if (path === PROFILE_PATH) {
    return (
      <AppShell user={user} onLogout={onLogout}>
        <ProfilePage currentUser={user} onUpdated={onUserUpdated} />
      </AppShell>
    )
  }

  const Page = user.role === 'adult' ? resolveAdultPage(path) : resolveChildPage(path)

  return (
    <AppShell user={user} onLogout={onLogout}>
      <Page />
    </AppShell>
  )
}

// The default pre-auth screen (Issue #22) is profile/PIN selection; the
// password form is a secondary route at /login/password. This needs its own
// path-based dispatch, so it gets its own RouterProvider -- independent of,
// and never mounted at the same time as, the authenticated tree's -- rather
// than a new routing library.
function AnonymousRouter({ onAuthenticated }: { onAuthenticated: (user: CurrentUser) => void }) {
  const { path } = useRouter()

  if (path === '/login/password') {
    return <PasswordLoginPage onLogin={onAuthenticated} />
  }
  return <ProfileLoginPage onLogin={onAuthenticated} />
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

  // Shared by every auth-completing action (password login, PIN login,
  // activation, PIN setup, and the initial session check): an existing
  // session whose user has never configured a PIN (Issue #22 -- only
  // reachable today via password login, or by reloading with such a session
  // still valid) is routed into mandatory PIN setup rather than the app,
  // regardless of which action produced it. Only the interactive
  // completion flows (login/pin-login/activate/pin-setup) also redirect to
  // the role's landing page -- the initial session-restore check below
  // deliberately does NOT reuse this for that part, since a reload/deep
  // link must keep whatever URL the user was already on, exactly like
  // before PIN login existed.
  const handleAuthSuccess = useCallback((user: CurrentUser) => {
    if (!user.pin_configured) {
      setAuth({ phase: 'pin-setup-required', user })
      return
    }
    // Dashboard is the landing page after a successful Adult login; Tasks
    // is the landing page for a Child.
    const landingPath = user.role === 'adult' ? '/dashboard' : '/tasks'
    if (window.location.pathname !== landingPath) {
      window.history.pushState({}, '', landingPath)
    }
    setAuth({ phase: 'authenticated', user })
  }, [])

  useEffect(() => {
    let cancelled = false

    me()
      .then((user) => {
        if (cancelled) return
        if (!user.pin_configured) {
          setAuth({ phase: 'pin-setup-required', user })
          return
        }
        setAuth({ phase: 'authenticated', user })
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

  function handleUserUpdated(user: CurrentUser) {
    setAuth({ phase: 'authenticated', user })
  }

  if (auth.phase === 'loading') {
    return <p>Loading...</p>
  }

  if (auth.phase === 'anonymous') {
    if (activationToken) {
      return <ActivationPage token={activationToken} onActivated={handleAuthSuccess} />
    }
    return (
      <RouterProvider>
        <AnonymousRouter onAuthenticated={handleAuthSuccess} />
      </RouterProvider>
    )
  }

  if (auth.phase === 'pin-setup-required') {
    return (
      <PinSetupRequiredPage
        user={auth.user}
        onComplete={handleAuthSuccess}
        onLogout={handleLogout}
      />
    )
  }

  return (
    <RouterProvider>
      <AuthenticatedApp
        user={auth.user}
        onLogout={handleLogout}
        onUserUpdated={handleUserUpdated}
      />
    </RouterProvider>
  )
}

export default App
