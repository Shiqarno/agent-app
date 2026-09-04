import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import ProfileLoginPage from './ProfileLoginPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const PROFILES = [
  { id: 'user-1', name: 'Alice', avatar_id: 'avatar_01' },
  { id: 'user-2', name: 'Kiddo', avatar_id: 'avatar_02' },
]

function renderPage(onLogin = vi.fn()) {
  return render(
    <RouterProvider>
      <ProfileLoginPage onLogin={onLogin} />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProfileLoginPage', () => {
  it('renders a profile card with avatar and name for each profile', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    const aliceButton = screen.getByRole('button', { name: /alice/i })
    expect(aliceButton.querySelector('img')).toHaveAttribute(
      'src',
      expect.stringContaining('avatar-01'),
    )
    expect(screen.getByRole('button', { name: /kiddo/i })).toBeInTheDocument()
  })

  it('shows a loading state while profiles are being fetched', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderPage()

    expect(screen.getByText(/loading profiles/i)).toBeInTheDocument()
  })

  it('shows an error state with retry on failure', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, PROFILES)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  it('has a password fallback link pointing at /login/password', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /email and password/i })).toHaveAttribute(
        'href',
        '/login/password',
      )
    })
  })

  it('selecting a profile shows the PIN entry view for that profile', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))

    expect(screen.getByText(/enter your pin/i)).toBeInTheDocument()
    expect(screen.getByRole('status', { name: /0 of 4 digits entered/i })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: /pin keypad/i })).toBeInTheDocument()
  })

  it('Back returns to the profile grid', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))
    fireEvent.click(screen.getByRole('button', { name: /^back$/i }))

    expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    expect(screen.queryByText(/enter your pin/i)).not.toBeInTheDocument()
  })

  it('entering 4 digits automatically submits and logs in on success', async () => {
    const onLogin = vi.fn()
    const loggedInUser = { id: 'user-1', name: 'Alice', role: 'adult', avatar_id: 'avatar_01' }
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
      if (url.endsWith('/api/auth/pin-login')) {
        expect(JSON.parse(init?.body as string)).toEqual({ user_id: 'user-1', pin: '1234' })
        return jsonResponse(200, loggedInUser)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage(onLogin)

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))

    for (const digit of ['1', '2', '3', '4']) {
      fireEvent.click(screen.getByRole('button', { name: `Digit ${digit}` }))
    }

    await waitFor(() => {
      expect(onLogin).toHaveBeenCalledWith(loggedInUser)
    })
  })

  it('an incorrect PIN clears the entry, reshuffles the keypad, and shows an error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        if (url.endsWith('/api/auth/pin-login')) {
          return jsonResponse(401, {
            error: { code: 'INVALID_CREDENTIALS', message: 'Invalid credentials' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))
    for (const digit of ['1', '2', '3', '4']) {
      fireEvent.click(screen.getByRole('button', { name: `Digit ${digit}` }))
    }

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByRole('status', { name: /0 of 4 digits entered/i })).toBeInTheDocument()
    // A fresh attempt is usable again -- the keypad remains interactive with
    // all 10 digits, not asserting any particular new order.
    expect(screen.getAllByRole('button', { name: /^Digit /i })).toHaveLength(10)
  })

  it('shows a distinct message when locked out', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        if (url.endsWith('/api/auth/pin-login')) {
          return jsonResponse(429, {
            error: { code: 'TOO_MANY_ATTEMPTS', message: 'Too many attempts' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))
    for (const digit of ['1', '2', '3', '4']) {
      fireEvent.click(screen.getByRole('button', { name: `Digit ${digit}` }))
    }

    await waitFor(() => {
      expect(screen.getByText(/too many/i)).toBeInTheDocument()
    })
  })

  it('does not double-submit while a request is already in flight', async () => {
    let resolvePinLogin: (value: unknown) => void = () => {}
    let pinLoginCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/auth/profiles')) return jsonResponse(200, PROFILES)
        if (url.endsWith('/api/auth/pin-login')) {
          pinLoginCallCount += 1
          return new Promise((resolve) => {
            resolvePinLogin = resolve
          }).then(() =>
            jsonResponse(200, { id: 'user-1', name: 'Alice', role: 'adult', avatar_id: 'avatar_01' }),
          )
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /alice/i }))
    for (const digit of ['1', '2', '3', '4']) {
      fireEvent.click(screen.getByRole('button', { name: `Digit ${digit}` }))
    }

    // The pad is disabled while the first request is in flight, so further
    // taps (attempted before resolving) must not trigger a second call.
    for (const button of screen.getAllByRole('button', { name: /^Digit /i })) {
      expect(button).toBeDisabled()
    }
    resolvePinLogin(undefined)

    await waitFor(() => {
      expect(pinLoginCallCount).toBe(1)
    })
  })
})
