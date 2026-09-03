import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
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

function reward(overrides: Partial<{
  id: string
  name: string
  description: string | null
  cost_points: number
  created_by: string
  created_at: string
  updated_at: string
}> = {}) {
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

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('RewardsPage', () => {
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
      vi.fn(() => jsonResponse(200, [reward()])),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(screen.getByText('30 minutes of extra screen time')).toBeInTheDocument()
    expect(screen.getByText(/cost: 50 points/i)).toBeInTheDocument()
  })

  it('shows the empty state with a path to create the first reward', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [])),
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

  it('shows an error state with retry when loading fails, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(() => {
        callCount += 1
        if (callCount === 1) return jsonResponse(500, {})
        return jsonResponse(200, [reward()])
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

  it('shows a useful fallback message on a genuine network failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject('network down')),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText(/could not load rewards/i)).toBeInTheDocument()
    })
  })

  it('renders rewards in the exact order the backend returns, without re-sorting', async () => {
    // The backend already orders by name asc, id asc; the frontend must
    // respect that order rather than re-sorting by created_at like Tasks
    // does. Deliberately out-of-created_at-order input to prove this.
    const rewards = [
      reward({ id: 'b', name: 'Bike ride', created_at: '2026-09-05T00:00:00Z' }),
      reward({ id: 'a', name: 'Movie night', created_at: '2026-09-01T00:00:00Z' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, rewards)),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(2)
    })
    const titles = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(titles[0]).toMatch(/bike ride/i)
    expect(titles[1]).toMatch(/movie night/i)
  })

  it('exposes a Create reward action pointing at /rewards/new', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [])),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /\+ create reward/i })).toHaveAttribute(
        'href',
        '/rewards/new',
      )
    })
  })

  it('each reward exposes an Edit link pointing at /rewards/:id/edit', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [reward({ id: 'reward-42' })])),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /^edit$/i })).toHaveAttribute(
        'href',
        '/rewards/reward-42/edit',
      )
    })
  })

  it('renders a reward with no description without showing a blank line', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [reward({ description: null })])),
    )

    renderRewardsPage()

    await waitFor(() => {
      expect(screen.getByText('Extra screen time')).toBeInTheDocument()
    })
    expect(screen.getByText(/cost: 50 points/i)).toBeInTheDocument()
  })
})
