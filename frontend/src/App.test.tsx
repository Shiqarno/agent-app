import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const ADULT_USER = {
  id: '11111111-1111-1111-1111-111111111111',
  name: 'Alice',
  role: 'adult',
  avatar_id: 'avatar_01',
  pin_configured: true,
}
const CHILD_USER = {
  id: '22222222-2222-2222-2222-222222222222',
  name: 'Kiddo',
  role: 'child',
  avatar_id: 'avatar_02',
  pin_configured: true,
}
const ADULT_PROFILE = { id: ADULT_USER.id, name: ADULT_USER.name, avatar_id: ADULT_USER.avatar_id }

// A default stub for the Dashboard's own data requests, reused by every test
// that reaches the authenticated Adult shell.
function stubDashboardData(url: string) {
  if (url.endsWith('/api/tasks')) {
    return jsonResponse(200, [])
  }
  if (url.endsWith('/api/task-executions')) {
    return jsonResponse(200, [])
  }
  if (url.endsWith('/api/points/balance')) {
    return jsonResponse(200, { balance: 0 })
  }
  if (url.endsWith('/api/users')) {
    return jsonResponse(200, [])
  }
  return undefined
}

// A default stub for the Rewards page's own data requests (rewards catalog
// + balance), reused by every test that reaches it as either role.
function stubRewardsData(url: string) {
  if (url.endsWith('/api/rewards')) {
    return jsonResponse(200, [])
  }
  if (url.endsWith('/api/points/balance')) {
    return jsonResponse(200, { balance: 0 })
  }
  if (url.endsWith('/api/points/history')) {
    return jsonResponse(200, [])
  }
  return undefined
}

// A default stub for the Tasks page's own data requests, reused by every
// Child test (Tasks is the Child's landing page as of Issue #15). /api/users
// genuinely 403s for a Child against the real backend (Adult-only); TasksPage
// already swallows that failure silently (assignee names are a presentation
// nicety), so this mirrors real backend behavior rather than papering over it.
function stubTasksData(url: string) {
  if (url.endsWith('/api/tasks')) {
    return jsonResponse(200, [])
  }
  if (url.endsWith('/api/task-executions')) {
    return jsonResponse(200, [])
  }
  if (url.endsWith('/api/users')) {
    return jsonResponse(403, { error: { code: 'FORBIDDEN', message: 'Forbidden' } })
  }
  return undefined
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('App', () => {
  it('shows a loading state before the session check resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    render(<App />)

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('shows the profile picker (default login screen) when there is no session', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /choose your profile/i })).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
  })

  it('logs in as an Adult via the password fallback and lands on the Dashboard', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      if (url.endsWith('/api/auth/login')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /email and password/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /email and password/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/dashboard')
  })

  it('logs in as a Child via the password fallback and lands on Tasks', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      if (url.endsWith('/api/auth/login')) {
        return jsonResponse(200, CHILD_USER)
      }
      const tasks = stubTasksData(url)
      if (tasks) return tasks
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /email and password/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /email and password/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kiddo@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText(/signed in as kiddo/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/tasks')
  })

  it('shows a login error on invalid credentials via the password fallback', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      if (url.endsWith('/api/auth/login')) {
        return jsonResponse(401, {
          error: { code: 'INVALID_CREDENTIALS', message: 'Invalid credentials' },
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /email and password/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /email and password/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid credentials')).toBeInTheDocument()
    })
  })

  it('logs in via PIN from the default profile picker and lands on the Dashboard', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      if (url.endsWith('/api/auth/pin-login')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))

    for (const digit of ['1', '2', '3', '4']) {
      fireEvent.click(screen.getByRole('button', { name: `Digit ${digit}` }))
    }

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/dashboard')
  })

  it('an existing user without a PIN is routed to mandatory PIN setup after password login, then to the app', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [])
      }
      if (url.endsWith('/api/auth/login')) {
        return jsonResponse(200, { ...ADULT_USER, pin_configured: false })
      }
      if (url.endsWith('/api/auth/pin') && init?.method === 'PATCH') {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /email and password/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /email and password/i }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /set up your pin/i })).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('link', { name: /skip/i }) ?? screen.queryByRole('button', { name: /skip/i }),
    ).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText(/choose a 4-digit pin/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/confirm your pin/i), { target: { value: '1234' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    expect(window.location.pathname).toBe('/dashboard')
  })

  it('a session without a configured PIN reloads into mandatory PIN setup, not the app', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, { ...ADULT_USER, pin_configured: false })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /set up your pin/i })).toBeInTheDocument()
    })
  })

  it('already-authenticated Adult session skips the login form and shows the Dashboard', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { name: /sign in/i })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
  })

  it('an authenticated Child does not receive the Adult Dashboard shell, and lands on Tasks', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      const tasks = stubTasksData(url)
      if (tasks) return tasks
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as kiddo/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { name: /^dashboard$/i })).not.toBeInTheDocument()
    // Content resolves to Tasks via the fallback route (unmatched/'/' -> Tasks
    // for a Child) -- same as how an Adult's session at '/' resolves to
    // Dashboard without the URL itself being rewritten.
    expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
  })

  it('a Child\'s navigation offers exactly Tasks, Rewards, and Points, no Adult-only sections', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      const tasks = stubTasksData(url)
      if (tasks) return tasks
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('navigation')).toBeInTheDocument()
    })
    const nav = screen.getByRole('navigation')
    expect(nav).toHaveTextContent('Tasks')
    expect(nav).toHaveTextContent('Rewards')
    expect(nav).toHaveTextContent('Points')
    expect(nav).not.toHaveTextContent('Dashboard')
    expect(nav).not.toHaveTextContent('Users')
  })

  it('a Child can navigate between Tasks, Rewards, and Points through the real router', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      const tasks = stubTasksData(url)
      if (tasks) return tasks
      const rewards = stubRewardsData(url)
      if (rewards) return rewards
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Rewards' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^rewards$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/rewards')

    fireEvent.click(screen.getByRole('link', { name: 'Points' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^points$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/points')

    fireEvent.click(screen.getByRole('link', { name: 'Tasks' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
    })
  })

  it.each([
    ['/dashboard', 'Dashboard'],
    ['/users', 'Users'],
    ['/tasks/new', 'Create task'],
  ])(
    'a Child navigating directly to the Adult-only route %s falls back to Tasks, not %s',
    async (adultPath) => {
      window.history.pushState({}, '', adultPath)
      const fetchMock = vi.fn((url: string) => {
        if (url.endsWith('/api/auth/me')) {
          return jsonResponse(200, CHILD_USER)
        }
        const tasks = stubTasksData(url)
        if (tasks) return tasks
        throw new Error(`Unexpected request: ${url}`)
      })
      vi.stubGlobal('fetch', fetchMock)

      render(<App />)

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
      })
      expect(screen.queryByRole('heading', { name: /^dashboard$/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: /^users$/i })).not.toBeInTheDocument()
      expect(screen.queryByRole('heading', { name: /^create task$/i })).not.toBeInTheDocument()
    },
  )

  it('navigating directly to an Adult route while unauthenticated shows Login, not the route', async () => {
    window.history.pushState({}, '', '/tasks')
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /choose your profile/i })).toBeInTheDocument()
    })
  })

  it('shows the activation form at /activate when a token is present in the URL', async () => {
    window.history.pushState({}, '', '/activate?activation_token=a-real-token')

    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/activate')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /activate your account/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kid@example.com' } })
    fireEvent.change(screen.getByLabelText(/^pin$/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/confirm pin/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: 'a-password-1' } })
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: 'a-password-1' },
    })
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })

    const [, activateInit] = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith('/api/auth/activate'),
    ) as [string, RequestInit]
    expect(JSON.parse(activateInit.body as string)).toEqual({
      token: 'a-real-token',
      email: 'kid@example.com',
      pin: '1234',
      password: 'a-password-1',
    })
  })

  it('activation succeeds with a PIN only, leaving password out of the request entirely', async () => {
    window.history.pushState({}, '', '/activate?activation_token=a-real-token')

    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/activate')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /activate your account/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'kid@example.com' } })
    fireEvent.change(screen.getByLabelText(/^pin$/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/confirm pin/i), { target: { value: '1234' } })
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })

    const [, activateInit] = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith('/api/auth/activate'),
    ) as [string, RequestInit]
    expect(JSON.parse(activateInit.body as string)).toEqual({
      token: 'a-real-token',
      email: 'kid@example.com',
      pin: '1234',
    })
  })

  it('logs out and returns to the default profile picker', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/auth/logout')) {
        return jsonResponse(204, undefined)
      }
      if (url.endsWith('/api/auth/profiles')) {
        return jsonResponse(200, [ADULT_PROFILE])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /log out/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /choose your profile/i })).toBeInTheDocument()
    })
  })

  it('primary navigation links move between Adult sections', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Points' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^points$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/points')

    fireEvent.click(screen.getByRole('link', { name: 'Dashboard' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })
  })

  it('Adult routing to /users renders the real User Management screen with activation status', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, [
          { id: 'u1', name: 'Active Alice', role: 'adult', activation_status: 'ACTIVE' },
          { id: 'u2', name: 'Pending Pat', role: 'child', activation_status: 'PENDING' },
        ])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Users' }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^users$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/users')
    expect(screen.getByText('Active Alice')).toBeInTheDocument()
    expect(screen.getByText('Pending Pat')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
  })

  it('Create task from the Dashboard Quick Action reaches NewTaskPage and returns to /dashboard', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: /create task/i }))

    // The Quick Action's link carries a "?from=dashboard" query string; the
    // router must still resolve /tasks/new (not silently fall back to
    // Dashboard) despite the query string.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^create task$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/tasks/new')
    expect(window.location.search).toBe('?from=dashboard')
  })

  it('/rewards -> /rewards/new renders the creation page through the real router', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/rewards')) {
        return jsonResponse(200, [])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Rewards' }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^rewards$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/rewards')

    fireEvent.click(screen.getByRole('link', { name: /\+ create reward/i }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^create reward$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/rewards/new')
  })

  it('clicking Edit on a Reward resolves the dynamic /rewards/:id/edit route through the real router', async () => {
    const existingReward = {
      id: 'reward-99',
      name: 'Movie night',
      description: 'Pick the movie',
      cost_points: 30,
      created_by: 'adult-1',
      created_at: '2026-09-03T10:00:00Z',
      updated_at: '2026-09-03T10:00:00Z',
    }
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/rewards')) {
        return jsonResponse(200, [existingReward])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Rewards' }))
    await waitFor(() => {
      expect(screen.getByText('Movie night')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: /^edit$/i }))

    // The router only matches static paths by default; /rewards/:id/edit is
    // the one dynamic route, resolved via a small pattern check in App.tsx.
    // This proves it actually renders EditRewardPage rather than falling
    // back to Dashboard.
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^edit reward$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/rewards/reward-99/edit')
    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Movie night')
    })
  })

  it("the Dashboard's own View history affordance navigates to /points", async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/points/history')) {
        return jsonResponse(200, [])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: /view history/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^points$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/points')
  })

  it('Adult: /tasks -> Details -> Edit -> Save resolves the dynamic Task routes through the real router', async () => {
    const existingTask = {
      id: 'task-99',
      title: 'Feed the cat',
      description: null,
      reward_points: 5,
      is_active: true,
      created_by: ADULT_USER.id,
      created_at: '2026-09-03T10:00:00Z',
      updated_at: '2026-09-03T10:00:00Z',
    }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/tasks') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, [existingTask])
      }
      if (url.endsWith('/api/tasks/task-99') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, existingTask)
      }
      if (url.endsWith('/api/tasks/task-99') && init?.method === 'PATCH') {
        return jsonResponse(200, { ...existingTask, title: 'Feed the cat and dog' })
      }
      if (url.endsWith('/api/task-executions')) {
        return jsonResponse(200, [])
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^dashboard$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: 'Tasks' }))
    await waitFor(() => {
      expect(screen.getByText('Feed the cat')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('link', { name: /details/i }))
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Feed the cat' })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/tasks/task-99')

    fireEvent.click(screen.getByRole('link', { name: /^edit$/i }))
    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Feed the cat')
    })
    expect(window.location.pathname).toBe('/tasks/task-99/edit')

    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: 'Feed the cat and dog' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks/task-99')
    })
  })

  it('Child can open Task Details for their own task, but /tasks/:id/edit falls back to Tasks', async () => {
    const childTask = {
      id: 'task-77',
      title: 'Walk the dog',
      description: null,
      reward_points: 5,
      is_active: true,
      created_by: ADULT_USER.id,
      created_at: '2026-09-03T10:00:00Z',
      updated_at: '2026-09-03T10:00:00Z',
    }
    const childExecution = {
      id: 'exec-77',
      task_id: 'task-77',
      user_id: CHILD_USER.id,
      status: 'ASSIGNED',
      reward_points: 5,
      created_at: '2026-09-03T10:00:00Z',
      updated_at: '2026-09-03T10:00:00Z',
    }
    window.history.pushState({}, '', '/tasks/task-77')
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      if (url.endsWith('/api/tasks/task-77')) {
        return jsonResponse(200, childTask)
      }
      if (url.endsWith('/api/task-executions')) {
        return jsonResponse(200, [childExecution])
      }
      const tasks = stubTasksData(url)
      if (tasks) return tasks
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    const { unmount } = render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Walk the dog' })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/tasks/task-77')
    // Assignee action available, but no creator-only management controls.
    expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
    unmount()

    window.history.pushState({}, '', '/tasks/task-77/edit')
    // Re-render fresh, as the router would resolve a direct navigation.
    render(<App />)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^tasks$/i })).toBeInTheDocument()
    })
  })

  // --- Avatars (Issue #20) -------------------------------------------------

  it('AppShell displays the current Adult\'s avatar', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.getByAltText(/your avatar/i)).toHaveAttribute(
      'src',
      expect.stringContaining('avatar-01'),
    )
  })

  it('marks the current destination as the active navigation link', async () => {
    window.history.pushState({}, '', '/dashboard')
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute(
        'aria-current',
        'page',
      )
    })
    expect(screen.getByRole('link', { name: 'Tasks' })).not.toHaveAttribute('aria-current')
  })

  it('renders the primary navigation with the responsive nav treatment', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('navigation')).toBeInTheDocument()
    })
    // The single nav landmark carries the class that switches between a
    // fixed bottom tab bar (phone) and a horizontal top bar (tablet+) via
    // CSS media queries -- jsdom does not compute real layout/visibility,
    // so this asserts the responsive hook is present rather than actual
    // rendered position at a given viewport size.
    expect(screen.getByRole('navigation')).toHaveClass('app-nav')
  })

  it('navigating to /profile for an Adult renders ProfilePage', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /your profile/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^profile$/i })).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/profile')
  })

  it('navigating to /profile for a Child renders ProfilePage too', async () => {
    window.history.pushState({}, '', '/profile')
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^profile$/i })).toBeInTheDocument()
    })
  })

  it('saving a new avatar on the Profile page updates the avatar AppShell displays, with no optimistic update beforehand', async () => {
    let resolvePatch: (value: unknown) => void = () => {}
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/users/me') && init?.method === 'PATCH') {
        expect(JSON.parse(init.body as string)).toEqual({ avatar_id: 'avatar_05' })
        return new Promise((resolve) => {
          resolvePatch = resolve
        }).then(() => jsonResponse(200, { ...ADULT_USER, avatar_id: 'avatar_05' }))
      }
      const dashboard = stubDashboardData(url)
      if (dashboard) return dashboard
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('link', { name: /your profile/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /^profile$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /avatar option avatar_05/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
    })
    // Still the pre-save avatar in the header -- no optimistic update.
    expect(screen.getByAltText(/your avatar/i)).toHaveAttribute(
      'src',
      expect.stringContaining('avatar-01'),
    )

    resolvePatch(undefined)

    await waitFor(() => {
      expect(screen.getByAltText(/your avatar/i)).toHaveAttribute(
        'src',
        expect.stringContaining('avatar-05'),
      )
    })
  })
})
