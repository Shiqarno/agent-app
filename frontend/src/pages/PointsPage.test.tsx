import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PointsPage from './PointsPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

function transaction(
  overrides: Partial<{
    id: string
    amount: number
    reason: 'TASK_COMPLETED' | 'REWARD_REDEEMED'
    task_id: string | null
    redemption_id: string | null
    created_at: string
  }> = {},
) {
  return {
    id: 'txn-1',
    amount: 20,
    reason: 'TASK_COMPLETED' as const,
    task_id: null,
    redemption_id: null,
    created_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function task(overrides: Partial<{ id: string; title: string }> = {}) {
  return {
    id: 'task-1',
    title: 'Clean your room',
    description: null,
    assigned_to: 'user-1',
    created_by: 'adult-1',
    reward_points: 20,
    status: 'COMPLETED',
    created_at: '2026-09-02T10:00:00Z',
    updated_at: '2026-09-02T10:00:00Z',
    ...overrides,
  }
}

// A default stub for /api/tasks (used only to enrich TASK_COMPLETED rows
// with a title), which every render requests regardless of scenario.
function baseHandlers(url: string) {
  if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
  return undefined
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PointsPage', () => {
  it('shows independent loading states for balance and history', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    render(<PointsPage />)

    expect(screen.getByText(/loading balance/i)).toBeInTheDocument()
    expect(screen.getByText(/loading history/i)).toBeInTheDocument()
  })

  it('renders the current balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 120 })
        if (url.endsWith('/api/points/history')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByText('120 points')).toBeInTheDocument()
    })
  })

  it('renders transaction history with positive and negative amounts distinguishable, and human-readable reasons', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 70 })
        if (url.endsWith('/api/points/history')) {
          return jsonResponse(200, [
            transaction({ id: 't1', amount: 20, reason: 'TASK_COMPLETED' }),
            transaction({ id: 't2', amount: -50, reason: 'REWARD_REDEEMED' }),
          ])
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    const items = await screen.findAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByText('+20 points')).toBeInTheDocument()
    expect(within(items[0]).getByText('Task completed')).toBeInTheDocument()
    expect(within(items[1]).getByText('-50 points')).toBeInTheDocument()
    expect(within(items[1]).getByText('Reward redeemed')).toBeInTheDocument()
    // Raw enum names are never shown directly.
    expect(screen.queryByText('TASK_COMPLETED')).not.toBeInTheDocument()
    expect(screen.queryByText('REWARD_REDEEMED')).not.toBeInTheDocument()
  })

  it('shows task context for a task-completion transaction when the API provides it', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 20 })
        if (url.endsWith('/api/points/history')) {
          return jsonResponse(200, [
            transaction({ id: 't1', amount: 20, reason: 'TASK_COMPLETED', task_id: 'task-1' }),
          ])
        }
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        return Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByText('"Clean your room"')).toBeInTheDocument()
    })
  })

  it('shows a redemption transaction without task context (no reward-name enrichment available)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 20 })
        if (url.endsWith('/api/points/history')) {
          return jsonResponse(200, [
            transaction({
              id: 't1',
              amount: -50,
              reason: 'REWARD_REDEEMED',
              redemption_id: 'redemption-1',
            }),
          ])
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByText('Reward redeemed')).toBeInTheDocument()
    })
    expect(screen.getByText('-50 points')).toBeInTheDocument()
  })

  it('shows the empty history state while still showing a successfully loaded zero balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/points/history')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByText('0 points')).toBeInTheDocument()
    })
    expect(screen.getByText(/no points history yet/i)).toBeInTheDocument()
  })

  it('shows a history error state with retry, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 50 })
        if (url.endsWith('/api/points/history')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, [transaction()])
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByText('Task completed')).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  it('a balance failure is never displayed as a zero balance', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(500, {})
        if (url.endsWith('/api/points/history')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.queryByText('0 points')).not.toBeInTheDocument()
  })

  it('a history failure is never displayed as an empty history', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 50 })
        if (url.endsWith('/api/points/history')) return jsonResponse(500, {})
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    render(<PointsPage />)

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.queryByText(/no points history yet/i)).not.toBeInTheDocument()
    // The independently-loaded balance remains visible.
    expect(screen.getByText('50 points')).toBeInTheDocument()
  })
})
