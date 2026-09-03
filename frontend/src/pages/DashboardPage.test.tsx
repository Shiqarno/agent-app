import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import DashboardPage from './DashboardPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const USERS = [
  { id: 'adult-1', name: 'Alice', role: 'adult' },
  { id: 'child-1', name: 'Kiddo', role: 'child' },
]

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    title: 'Tidy the room',
    description: null,
    assigned_to: 'child-1',
    created_by: 'adult-1',
    reward_points: 10,
    status: 'ASSIGNED',
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function renderDashboard() {
  return render(
    <RouterProvider>
      <DashboardPage />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('DashboardPage', () => {
  it('shows an explicit loading state per section before data resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderDashboard()

    const loadingTexts = screen.getAllByText(/loading/i)
    // Pending tasks, Recent tasks, and Points each render their own
    // "Loading..." independently of one another.
    expect(loadingTexts.length).toBeGreaterThanOrEqual(3)
  })

  it('shows only AWAITING_CONFIRMATION tasks in the pending-confirmation block', async () => {
    const tasks = [
      task({ id: 'pending-1', title: 'Needs confirmation', status: 'AWAITING_CONFIRMATION' }),
      task({ id: 'in-progress-1', title: 'Still working', status: 'IN_PROGRESS' }),
      task({ id: 'assigned-1', title: 'Not started', status: 'ASSIGNED' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 5 })
        if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    const pendingSection = await screen.findByRole('heading', {
      name: /tasks requiring attention/i,
    })
    const pending = pendingSection.closest('section') as HTMLElement
    await waitFor(() => {
      expect(within(pending).getByText(/needs confirmation/i)).toBeInTheDocument()
    })
    expect(within(pending).queryByText(/still working/i)).not.toBeInTheDocument()
    expect(within(pending).queryByText(/not started/i)).not.toBeInTheDocument()
  })

  it('shows the empty state when there are no pending confirmations', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText(/no tasks waiting for confirmation/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/no tasks yet/i)).toBeInTheDocument()
  })

  it('confirming a pending task calls the existing transition and refreshes tasks and points', async () => {
    const pendingTask = task({ id: 'pending-1', title: 'Needs confirmation', status: 'AWAITING_CONFIRMATION' })
    let tasksCallCount = 0
    let balanceCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks')) {
        tasksCallCount += 1
        // After confirmation, the task is no longer AWAITING_CONFIRMATION.
        const body = tasksCallCount === 1 ? [pendingTask] : [{ ...pendingTask, status: 'COMPLETED' }]
        return jsonResponse(200, body)
      }
      if (url.endsWith('/api/points/balance')) {
        balanceCallCount += 1
        return jsonResponse(200, { balance: balanceCallCount === 1 ? 0 : 10 })
      }
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, USERS)
      }
      if (url.endsWith('/api/tasks/pending-1/confirm')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, { ...pendingTask, status: 'COMPLETED' })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument()
    })
    expect(screen.getByText('0')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(screen.getByText(/no tasks waiting for confirmation/i)).toBeInTheDocument()
    })
    await waitFor(() => {
      expect(screen.getByText('10')).toBeInTheDocument()
    })
    expect(fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/tasks'))).toHaveLength(2)
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/points/balance')),
    ).toHaveLength(2)
  })

  it('keeps a task visible with an error if confirmation fails', async () => {
    const pendingTask = task({ id: 'pending-1', title: 'Needs confirmation', status: 'AWAITING_CONFIRMATION' })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [pendingTask])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
        if (url.endsWith('/api/tasks/pending-1/confirm')) {
          return jsonResponse(409, {
            error: { code: 'INVALID_TRANSITION', message: 'Cannot confirm this task' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /confirm/i }))

    await waitFor(() => {
      expect(screen.getByText('Cannot confirm this task')).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /confirm/i })).toBeInTheDocument()
  })

  it('shows the 5 most recent tasks ordered by created_at desc, id desc, read-only', async () => {
    const tasks = [
      task({ id: 'a', title: 'Oldest', created_at: '2026-09-01T00:00:00Z' }),
      task({ id: 'b', title: 'Second', created_at: '2026-09-02T00:00:00Z' }),
      task({ id: 'c', title: 'Third', created_at: '2026-09-03T00:00:00Z' }),
      task({ id: 'd', title: 'Fourth', created_at: '2026-09-04T00:00:00Z' }),
      task({ id: 'e', title: 'Fifth', created_at: '2026-09-05T00:00:00Z' }),
      task({ id: 'f', title: 'Newest', created_at: '2026-09-06T00:00:00Z' }),
      // Same created_at as "Newest" -- tie broken by id desc.
      task({ id: 'g', title: 'Tied but higher id', created_at: '2026-09-06T00:00:00Z' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    const heading = await screen.findByRole('heading', { name: /recent tasks/i })
    const section = heading.closest('section') as HTMLElement
    await waitFor(() => {
      expect(within(section).getAllByRole('listitem')).toHaveLength(5)
    })
    const titles = within(section)
      .getAllByRole('listitem')
      .map((item) => item.textContent)
    expect(titles[0]).toMatch(/tied but higher id/i)
    expect(titles[1]).toMatch(/newest/i)
    expect(titles[2]).toMatch(/fifth/i)
    expect(titles[3]).toMatch(/fourth/i)
    expect(titles[4]).toMatch(/third/i)
    expect(titles.some((t) => t?.match(/oldest/i))).toBe(false)
    // Read-only: no action controls in this section.
    expect(within(section).queryByRole('button')).not.toBeInTheDocument()
  })

  it('displays the personal points balance and a history navigation link', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 42 })
        if (url.endsWith('/api/users')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByText('42')).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /view history/i })).toHaveAttribute('href', '/points')
  })

  it('exposes Quick Actions for creating a task, adding a user, and creating a reward', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /create task/i })).toHaveAttribute(
        'href',
        '/tasks/new',
      )
    })
    expect(screen.getByRole('link', { name: /add user/i })).toHaveAttribute('href', '/users/new')
    expect(screen.getByRole('link', { name: /create reward/i })).toHaveAttribute(
      'href',
      '/rewards/new',
    )
  })

  it('a failed section shows a retry action without hiding successful sections', async () => {
    let tasksCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          tasksCallCount += 1
          if (tasksCallCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, [])
        }
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 7 })
        if (url.endsWith('/api/users')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getAllByRole('alert').length).toBeGreaterThan(0)
    })
    // Points and Quick Actions remain available despite the tasks failure.
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /create task/i })).toBeInTheDocument()

    const [retryButton] = screen.getAllByRole('button', { name: /retry/i })
    fireEvent.click(retryButton)

    await waitFor(() => {
      expect(screen.getByText(/no tasks waiting for confirmation/i)).toBeInTheDocument()
    })
  })
})
