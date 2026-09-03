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

const ADULT_USER = { id: '11111111-1111-1111-1111-111111111111', name: 'Alice', role: 'adult' }
const CHILD_USER = { id: '22222222-2222-2222-2222-222222222222', name: 'Kiddo', role: 'child' }

// A default stub for the Dashboard's own data requests, reused by every test
// that reaches the authenticated Adult shell.
function stubDashboardData(url: string) {
  if (url.endsWith('/api/tasks')) {
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

  it('shows the login form when there is no session', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })
  })

  it('logs in as an Adult and lands on the Dashboard', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
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

  it('shows a login error on invalid credentials', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
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
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong-password' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid credentials')).toBeInTheDocument()
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

  it('an authenticated Child does not receive the Adult Dashboard shell', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CHILD_USER)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as kiddo/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { name: /^dashboard$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('navigation')).not.toBeInTheDocument()
  })

  it('navigating directly to an Adult route while unauthenticated shows Login, not the route', async () => {
    window.history.pushState({}, '', '/tasks')
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
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
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password-1' } })
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
      password: 'a-password-1',
    })
  })

  it('logs out and returns to the login form', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, ADULT_USER)
      }
      if (url.endsWith('/api/auth/logout')) {
        return jsonResponse(204, undefined)
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
      expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
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
})
