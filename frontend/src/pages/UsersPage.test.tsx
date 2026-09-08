import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { activationTelegramUrlFor } from '../api/users'
import { RouterProvider } from '../router'
import UsersPage from './UsersPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

function user(
  overrides: Partial<{
    id: string
    name: string
    role: string
    avatar_id: string
    activation_status: string
    telegram_connected: boolean
  }> = {},
) {
  return {
    id: 'user-1',
    name: 'Alice',
    role: 'adult',
    avatar_id: 'avatar_04',
    activation_status: 'ACTIVE',
    telegram_connected: false,
    ...overrides,
  }
}

function renderUsersPage() {
  return render(
    <RouterProvider>
      <UsersPage />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe('UsersPage', () => {
  // --- List loading -----------------------------------------------------------

  it('shows an explicit loading state before the user list resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderUsersPage()

    expect(screen.getByText(/loading users/i)).toBeInTheDocument()
  })

  it('renders the loaded user list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user()])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument()
    })
    expect(screen.getByText(/role: adult/i)).toBeInTheDocument()
  })

  it('renders an avatar for each user in the list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ avatar_id: 'avatar_07' })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument()
    })
    const card = screen.getByText('Alice').closest('li') as HTMLElement
    expect(within(card).getByRole('img')).toHaveAttribute('src', expect.stringContaining('avatar-07'))
  })

  it('shows the empty state when there are no users', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText(/no users yet/i)).toBeInTheDocument()
    })
  })

  it('shows an error state with retry when loading fails, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        callCount += 1
        if (callCount === 1) return jsonResponse(500, {})
        return jsonResponse(200, [user()])
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  // --- Activation status rendering ---------------------------------------------

  it('renders Active status correctly', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ activation_status: 'ACTIVE' })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument()
    })
    // Raw enum value is never shown on its own.
    expect(screen.queryByText('ACTIVE')).not.toBeInTheDocument()
  })

  it('renders Pending activation status correctly, with a Generate link action', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ activation_status: 'PENDING' })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Pending activation')).toBeInTheDocument()
    })
    expect(screen.queryByText('PENDING')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
  })

  it('active users do not have a Generate link action', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ activation_status: 'ACTIVE' })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Alice')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /generate activation link/i }),
    ).not.toBeInTheDocument()
  })

  // --- Regeneration --------------------------------------------------------------

  it('clicking Generate calls the regeneration endpoint for that user', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/users')) return jsonResponse(200, [user({ activation_status: 'PENDING' })])
      if (url.endsWith('/api/users/user-1/activation')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, {
          activation_token: 'raw-new-token',
          expires_at: '2026-09-06T12:00:00Z',
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/activation')),
      ).toHaveLength(1)
    })
  })

  it('disables the action while the request is pending', async () => {
    let resolveRegenerate: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, [user({ activation_status: 'PENDING' })])
        if (url.endsWith('/api/users/user-1/activation')) {
          return new Promise((resolve) => {
            resolveRegenerate = () =>
              resolve({
                ok: true,
                status: 200,
                json: () =>
                  Promise.resolve({
                    activation_token: 'raw-new-token',
                    expires_at: '2026-09-06T12:00:00Z',
                  }),
              })
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
    })

    resolveRegenerate()
    await waitFor(() => {
      expect(screen.getByText(/raw-new-token/i)).toBeInTheDocument()
    })
  })

  it('displays the generated activation link and expiration on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, [user({ activation_status: 'PENDING' })])
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'raw-new-token',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(
        screen.getByText(`${window.location.origin}/activate?activation_token=raw-new-token`),
      ).toBeInTheDocument()
    })
    expect(screen.getByText(/expires:/i)).toBeInTheDocument()
  })

  it('the Copy link action copies the generated link', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, [user({ activation_status: 'PENDING' })])
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'raw-new-token',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.origin}/activate?activation_token=raw-new-token`,
      )
    })
  })

  it('displays an API error and leaves the user list usable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, [user({ activation_status: 'PENDING' })])
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(500, {})
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    // The list itself is not removed or corrupted by the failure.
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /generate activation link/i })).toBeEnabled()
  })

  it('USER_ALREADY_ACTIVATED refreshes the list so status reflects reality', async () => {
    let listCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          listCallCount += 1
          const status = listCallCount === 1 ? 'PENDING' : 'ACTIVE'
          return jsonResponse(200, [user({ activation_status: status })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(409, {
            error: { code: 'USER_ALREADY_ACTIVATED', message: 'User already activated' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generate activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(screen.getByText('Active')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /generate activation link/i }),
    ).not.toBeInTheDocument()
    expect(listCallCount).toBe(2)
  })

  it('regeneration for one user does not affect another user in the same list', async () => {
    const users = [
      user({ id: 'user-1', name: 'Alice', activation_status: 'PENDING' }),
      user({ id: 'user-2', name: 'Bob', activation_status: 'PENDING' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, users)
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'token-for-alice',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /generate activation link/i })).toHaveLength(2)
    })

    const aliceItem = screen.getByText('Alice').closest('li') as HTMLElement
    fireEvent.click(within(aliceItem).getByRole('button', { name: /generate activation link/i }))

    await waitFor(() => {
      expect(within(aliceItem).getByText(/token-for-alice/i)).toBeInTheDocument()
    })
    const bobItem = screen.getByText('Bob').closest('li') as HTMLElement
    expect(within(bobItem).queryByText(/activate\?activation_token=/i)).not.toBeInTheDocument()
    expect(
      within(bobItem).getByRole('button', { name: /generate activation link/i }),
    ).toBeEnabled()
  })

  // --- Regression: Add User navigation still available ----------------------------

  it('the Add user action still exists', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /add user/i })).toHaveAttribute('href', '/users/new')
    })
  })

  // --- Telegram activation link (Issue #33) ---------------------------------------

  it('an unconnected Child shows Not connected and offers Get activation link', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ role: 'child', telegram_connected: false })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Not connected')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
  })

  it('a connected Child shows Connected and does not offer Get activation link', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ role: 'child', telegram_connected: true })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /get activation link/i }),
    ).not.toBeInTheDocument()
  })

  it('a Connected Child never calls the activation endpoint', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, [user({ role: 'child', telegram_connected: true })])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument()
    })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/activation'))).toBe(false)
  })

  // --- Issue #34: Telegram activation is role-independent -------------------------

  it('an unconnected Adult shows Not connected and offers Get activation link', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ role: 'adult', telegram_connected: false })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Not connected')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
  })

  it('a connected Adult shows Connected and does not offer Get activation link', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [user({ role: 'adult', telegram_connected: true })])),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /get activation link/i }),
    ).not.toBeInTheDocument()
  })

  it('a Connected Adult never calls the activation endpoint', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, [user({ role: 'adult', telegram_connected: true })])
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument()
    })
    expect(fetchMock.mock.calls.some(([url]) => String(url).endsWith('/activation'))).toBe(false)
  })

  it('clicking Get activation link for an Adult calls the activation endpoint and shows a Telegram deep link', async () => {
    const expectedUrl = activationTelegramUrlFor('raw-adult-token')
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, [user({ role: 'adult', telegram_connected: false })])
      }
      if (url.endsWith('/api/users/user-1/activation')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, {
          activation_token: 'raw-adult-token',
          expires_at: '2026-09-06T12:00:00Z',
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByText(expectedUrl)).toBeInTheDocument()
    })
    expect(screen.getByText(/expires:/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open in telegram/i })).toHaveAttribute(
      'href',
      expectedUrl,
    )
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/activation')),
    ).toHaveLength(1)
  })

  it('the Copy link action copies the generated Telegram link for an Adult', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          return jsonResponse(200, [user({ role: 'adult', telegram_connected: false })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'raw-adult-token',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(activationTelegramUrlFor('raw-adult-token'))
    })
  })

  it('generating a Telegram link for an Adult does not affect a Child in the same list', async () => {
    const users = [
      user({ id: 'user-1', name: 'Alice', role: 'adult', telegram_connected: false }),
      user({ id: 'user-2', name: 'Bob', role: 'child', telegram_connected: false }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, users)
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'token-for-alice',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /get activation link/i })).toHaveLength(2)
    })

    const aliceItem = screen.getByText('Alice').closest('li') as HTMLElement
    fireEvent.click(within(aliceItem).getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(within(aliceItem).getByText(/token-for-alice/i)).toBeInTheDocument()
    })
    const bobItem = screen.getByText('Bob').closest('li') as HTMLElement
    expect(within(bobItem).queryByText(/t\.me\//i)).not.toBeInTheDocument()
    expect(within(bobItem).getByText('Not connected')).toBeInTheDocument()
    expect(
      within(bobItem).getByRole('button', { name: /get activation link/i }),
    ).toBeEnabled()
  })

  it('clicking Get activation link calls the activation endpoint and shows a Telegram deep link', async () => {
    const expectedUrl = activationTelegramUrlFor('raw-telegram-token')
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, [user({ role: 'child', telegram_connected: false })])
      }
      if (url.endsWith('/api/users/user-1/activation')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, {
          activation_token: 'raw-telegram-token',
          expires_at: '2026-09-06T12:00:00Z',
        })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByText(expectedUrl)).toBeInTheDocument()
    })
    expect(screen.getByText(/expires:/i)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /open in telegram/i })).toHaveAttribute(
      'href',
      expectedUrl,
    )
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/activation')),
    ).toHaveLength(1)
  })

  it('disables the Telegram action while the request is pending', async () => {
    let resolveRequest: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          return jsonResponse(200, [user({ role: 'child', telegram_connected: false })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return new Promise((resolve) => {
            resolveRequest = () =>
              resolve({
                ok: true,
                status: 200,
                json: () =>
                  Promise.resolve({
                    activation_token: 'raw-telegram-token',
                    expires_at: '2026-09-06T12:00:00Z',
                  }),
              })
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()
    })

    resolveRequest()
    await waitFor(() => {
      expect(screen.getByText(/raw-telegram-token/i)).toBeInTheDocument()
    })
  })

  it('the Copy link action copies the generated Telegram link', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          return jsonResponse(200, [user({ role: 'child', telegram_connected: false })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'raw-telegram-token',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(activationTelegramUrlFor('raw-telegram-token'))
    })
  })

  it('generating a second Telegram link calls the endpoint again and shows the new link', async () => {
    let activationCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          return jsonResponse(200, [user({ role: 'child', telegram_connected: false })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          activationCallCount += 1
          return jsonResponse(200, {
            activation_token: activationCallCount === 1 ? 'link-a-token' : 'link-b-token',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))
    await waitFor(() => {
      expect(screen.getByText(/link-a-token/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))
    await waitFor(() => {
      expect(screen.getByText(/link-b-token/i)).toBeInTheDocument()
    })
    expect(screen.queryByText(/link-a-token/i)).not.toBeInTheDocument()
    expect(activationCallCount).toBe(2)
  })

  it('displays an API error for the Telegram action and leaves the user list usable', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          return jsonResponse(200, [user({ role: 'child', telegram_connected: false })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(500, {})
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.getByText('Alice')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /get activation link/i })).toBeEnabled()
    // A failed generation must never leave a fake link displayed.
    expect(screen.queryByRole('link', { name: /open in telegram/i })).not.toBeInTheDocument()
  })

  it('USER_ALREADY_ACTIVATED for the Telegram action refreshes the list', async () => {
    let listCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) {
          listCallCount += 1
          const connected = listCallCount > 1
          return jsonResponse(200, [user({ role: 'child', telegram_connected: connected })])
        }
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(409, {
            error: { code: 'USER_ALREADY_ACTIVATED', message: 'User already activated' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /get activation link/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(screen.getByText('Connected')).toBeInTheDocument()
    })
    expect(
      screen.queryByRole('button', { name: /get activation link/i }),
    ).not.toBeInTheDocument()
    expect(listCallCount).toBe(2)
  })

  it('generating a Telegram link for one user does not affect another user in the same list', async () => {
    const users = [
      user({ id: 'user-1', name: 'Alice', role: 'child', telegram_connected: false }),
      user({ id: 'user-2', name: 'Bob', role: 'child', telegram_connected: false }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, users)
        if (url.endsWith('/api/users/user-1/activation')) {
          return jsonResponse(200, {
            activation_token: 'token-for-alice',
            expires_at: '2026-09-06T12:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderUsersPage()

    await waitFor(() => {
      expect(screen.getAllByRole('button', { name: /get activation link/i })).toHaveLength(2)
    })

    const aliceItem = screen.getByText('Alice').closest('li') as HTMLElement
    fireEvent.click(within(aliceItem).getByRole('button', { name: /get activation link/i }))

    await waitFor(() => {
      expect(within(aliceItem).getByText(/token-for-alice/i)).toBeInTheDocument()
    })
    const bobItem = screen.getByText('Bob').closest('li') as HTMLElement
    expect(within(bobItem).queryByText(/t\.me\//i)).not.toBeInTheDocument()
    expect(
      within(bobItem).getByRole('button', { name: /get activation link/i }),
    ).toBeEnabled()
  })
})
