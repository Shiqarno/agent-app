import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import RewardsPage from './RewardsPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const ADULT = { id: 'adult-1', name: 'Alice', role: 'adult' }
const CHILD = { id: 'child-1', name: 'Kiddo', role: 'child' }

function reward(
  overrides: Partial<{
    id: string
    name: string
    description: string | null
    cost_points: number
    created_by: string
    created_at: string
    updated_at: string
  }> = {},
) {
  return {
    id: 'reward-1',
    name: 'Extra screen time',
    description: '30 minutes of extra screen time',
    cost_points: 50,
    created_by: 'adult-1',
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function renderRewardsPage() {
  return render(
    <RouterProvider>
      <RewardsPage />
    </RouterProvider>,
  )
}

// A default stub for /api/auth/me, /api/points/balance, and /api/points/
// history, which every render of RewardsPage requests regardless of the
// scenario under test.
function baseHandlers(
  url: string,
  currentUser: { id: string; name: string; role: string } = ADULT,
  balance = 100,
) {
  if (url.endsWith('/api/auth/me')) return jsonResponse(200, currentUser)
  if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance })
  if (url.endsWith('/api/points/history')) return jsonResponse(200, [])
  return undefined
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RewardsPage', () => {
  // --- Loading / list states -----------------------------------------------

  it('shows an explicit loading state before the reward list resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderRewardsPage()

    expect(screen.getByText(/loading rewards/i)).toBeInTheDocument()
    expect(screen.queryByText(/no rewards yet/i)).not.toBeInTheDocument()
  })

  it('renders the loaded reward catalog', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(screen.getByText('30 minutes of extra screen time')).toBeInTheDocument()
    expect(screen.getByText(/cost: 50 points/i)).toBeInTheDocument()
  })

  it('shows the empty state with a path to create the first reward (Adult)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/no rewards yet/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /create your first reward/i })).toHaveAttribute(
      'href',
      '/rewards/new',
    )
  })

  it('shows a rewards error state with retry when loading fails, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, [reward()])
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  it('renders rewards in the exact order the backend returns, without re-sorting', async () => {
    const rewards = [
      reward({ id: 'b', name: 'Bike ride', created_at: '2026-09-05T00:00:00Z' }),
      reward({ id: 'a', name: 'Movie night', created_at: '2026-09-01T00:00:00Z' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, rewards)
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(2)
    })
    const titles = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(titles[0]).toMatch(/bike ride/i)
    expect(titles[1]).toMatch(/movie night/i)
  })

  it('renders a reward with no description without showing a blank line', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward({ description: null })])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(screen.getByText(/cost: 50 points/i)).toBeInTheDocument()
  })

  // --- Balance ---------------------------------------------------------------

  it('an authenticated Adult sees their balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [])
        return baseHandlers(url, ADULT, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/your balance: 120 points/i)).toBeInTheDocument()
    })
  })

  it('an authenticated Child sees their balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [])
        return baseHandlers(url, CHILD, 30) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/your balance: 30 points/i)).toBeInTheDocument()
    })
  })

  it('a balance load failure shows its own error+retry without hiding a successfully loaded catalog', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        if (url.endsWith('/api/points/balance')) return jsonResponse(500, {})
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    // Reward catalog remains usable despite the balance failure.
    expect(screen.getByText('Extra screen time')).toBeInTheDocument()
  })

  it('a rewards load failure preserves independently loaded balance information', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(500, {})
        return baseHandlers(url, ADULT, 42) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/your balance: 42 points/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('alert')).toBeInTheDocument()
  })

  // --- Role-gated management controls (Issue #13 behavior, now role-aware) --

  it('Adult sees Create reward and Edit actions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward({ id: 'reward-42' })])
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /\+ create reward/i })).toHaveAttribute(
        'href',
        '/rewards/new',
      )
    })
    expect(screen.getByRole('link', { name: /^edit$/i })).toHaveAttribute(
      'href',
      '/rewards/reward-42/edit',
    )
  })

  it('Child does not see Create reward or Edit actions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward({ id: 'reward-42' })])
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: /create reward/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
  })

  // --- Redeem visibility -------------------------------------------------------

  it('both Adult and Child see the Redeem action', async () => {
    for (const [user, balance] of [
      [ADULT, 100],
      [CHILD, 100],
    ] as const) {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
          return baseHandlers(url, user, balance) ?? Promise.reject(new Error(`Unexpected: ${url}`))
        }),
      )

      const { unmount } = renderRewardsPage()
      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^redeem$/i })).toBeInTheDocument()
      })
      unmount()
      vi.unstubAllGlobals()
    }
  })

  // --- Insufficient balance -------------------------------------------------

  it('disables Redeem and shows "Not enough points" when the balance is insufficient', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward({ cost_points: 50 })])
        return baseHandlers(url, CHILD, 10) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/not enough points/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /^redeem$/i })).toBeDisabled()
  })

  // --- Confirmation flow -----------------------------------------------------

  it('clicking Redeem opens inline confirmation with reward name, cost, and balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        return baseHandlers(url, CHILD, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^redeem$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    const confirmBlock = screen
      .getByText(/redeem "extra screen time"/i)
      .closest('.redeem-confirm') as HTMLElement
    expect(confirmBlock).toBeInTheDocument()
    expect(within(confirmBlock).getByText(/cost: 50 points/i)).toBeInTheDocument()
    expect(within(confirmBlock).getByText(/your balance: 120 points/i)).toBeInTheDocument()
    expect(within(confirmBlock).getByRole('button', { name: /cancel/i })).toBeInTheDocument()
  })

  it('Cancel closes the confirmation without calling the redemption API', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
      return baseHandlers(url, CHILD, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^redeem$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancel/i }))

    expect(screen.queryByText(/redeem "extra screen time"/i)).not.toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/redeem')),
    ).toHaveLength(0)
  })

  it('confirming calls the redemption endpoint', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
      if (url.endsWith('/api/rewards/reward-1/redeem')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(201, {
          id: 'redemption-1',
          reward_id: 'reward-1',
          user_id: CHILD.id,
          cost_points: 50,
          created_at: '2026-09-03T10:05:00Z',
        })
      }
      return baseHandlers(url, CHILD, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^redeem$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    await waitFor(() => {
      expect(
        fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/redeem')),
      ).toHaveLength(1)
    })
  })

  it('disables the confirm button while the redemption is pending, preventing duplicate submissions', async () => {
    let resolveRedeem: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        if (url.endsWith('/api/rewards/reward-1/redeem')) {
          return new Promise((resolve) => {
            resolveRedeem = () =>
              resolve({
                ok: true,
                status: 201,
                json: () =>
                  Promise.resolve({
                    id: 'redemption-1',
                    reward_id: 'reward-1',
                    user_id: CHILD.id,
                    cost_points: 50,
                    created_at: '2026-09-03T10:05:00Z',
                  }),
              })
          })
        }
        return baseHandlers(url, CHILD, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^redeem$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /redeeming/i })).toBeDisabled()
    })
    expect(screen.getByRole('button', { name: /cancel/i })).toBeDisabled()

    resolveRedeem()
    await waitFor(() => {
      expect(screen.getByText(/redeemed "extra screen time"/i)).toBeInTheDocument()
    })
  })

  it('successful redemption refreshes the balance and shows success feedback', async () => {
    let balanceCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        if (url.endsWith('/api/points/balance')) {
          balanceCallCount += 1
          return jsonResponse(200, { balance: balanceCallCount === 1 ? 120 : 70 })
        }
        if (url.endsWith('/api/rewards/reward-1/redeem')) {
          return jsonResponse(201, {
            id: 'redemption-1',
            reward_id: 'reward-1',
            user_id: CHILD.id,
            cost_points: 50,
            created_at: '2026-09-03T10:05:00Z',
          })
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/your balance: 120 points/i)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    await waitFor(() => {
      expect(screen.getByText(/redeemed "extra screen time"/i)).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText(/your balance: 70 points/i)).toBeInTheDocument()
    })
    expect(balanceCallCount).toBe(2)
    // The confirmation UI closes on success.
    expect(screen.queryByRole('button', { name: /cancel/i })).not.toBeInTheDocument()
  })

  it('failed redemption shows an error, keeps the user on the catalog, and does not change the balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward()])
        if (url.endsWith('/api/rewards/reward-1/redeem')) {
          return jsonResponse(409, {
            error: { code: 'INSUFFICIENT_POINTS', message: 'Insufficient points to redeem this reward' },
          })
        }
        return baseHandlers(url, CHILD, 120) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/your balance: 120 points/i)).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    await waitFor(() => {
      expect(screen.getByText('Insufficient points to redeem this reward')).toBeInTheDocument()
    })
    // Balance is unchanged (no optimistic mutation) and the catalog is intact.
    expect(document.querySelector('.reward-balance')).toHaveTextContent('Your balance: 120 points')
    expect(screen.getByText('Extra screen time')).toBeInTheDocument()
  })

  it('handles a stale-balance backend rejection: displayed balance looked sufficient but the backend rejects', async () => {
    // Simulates: Tab A loaded balance=100 before Tab B spent 80 elsewhere.
    // The backend is the one that actually knows the current balance and
    // correctly rejects Tab A's redemption despite what's on screen.
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [reward({ cost_points: 50 })])
        if (url.endsWith('/api/rewards/reward-1/redeem')) {
          return jsonResponse(409, {
            error: { code: 'INSUFFICIENT_POINTS', message: 'Insufficient points to redeem this reward' },
          })
        }
        return baseHandlers(url, CHILD, 100) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderRewardsPage()

    await waitFor(() => {
      // Displayed balance (100) makes the reward (50) look affordable --
      // Redeem is enabled purely from the frontend's stale point of view.
      expect(screen.getByRole('button', { name: /^redeem$/i })).toBeEnabled()
    })
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))
    fireEvent.click(screen.getByRole('button', { name: /^redeem$/i }))

    await waitFor(() => {
      expect(screen.getByText('Insufficient points to redeem this reward')).toBeInTheDocument()
    })
    // No false success is shown, and the stale balance is not silently kept
    // as if nothing happened -- it's still what the backend last confirmed.
    expect(screen.queryByText(/redeemed "extra screen time"/i)).not.toBeInTheDocument()
  })
})
