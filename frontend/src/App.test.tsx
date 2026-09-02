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

const CURRENT_USER = { id: '11111111-1111-1111-1111-111111111111', name: 'Alice', role: 'adult' }

afterEach(() => {
  vi.unstubAllGlobals()
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

  it('logs in and shows the authenticated app', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/login')) {
        return jsonResponse(200, CURRENT_USER)
      }
      if (url.endsWith('/api/projects')) {
        return jsonResponse(200, [])
      }
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
    expect(screen.getByRole('heading', { name: /projects/i })).toBeInTheDocument()
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

  it('already-authenticated session skips the login form', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CURRENT_USER)
      }
      if (url.endsWith('/api/projects')) {
        return jsonResponse(200, [])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/signed in as alice/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('heading', { name: /sign in/i })).not.toBeInTheDocument()
  })

  it('shows the activation form when an activation token is present in the URL', async () => {
    const originalLocation = window.location.href
    window.history.pushState({}, '', '/?activation_token=a-real-token')

    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(401, { error: { code: 'UNAUTHENTICATED', message: 'nope' } })
      }
      if (url.endsWith('/api/auth/activate')) {
        return jsonResponse(200, CURRENT_USER)
      }
      if (url.endsWith('/api/projects')) {
        return jsonResponse(200, [])
      }
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    try {
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
    } finally {
      window.history.pushState({}, '', originalLocation)
    }
  })

  it('logs out and returns to the login form', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/me')) {
        return jsonResponse(200, CURRENT_USER)
      }
      if (url.endsWith('/api/projects')) {
        return jsonResponse(200, [])
      }
      if (url.endsWith('/api/auth/logout')) {
        return jsonResponse(204, undefined)
      }
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
})
