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
    reward_points: 10,
    is_active: true,
    created_by: 'adult-1',
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function execution(overrides: Record<string, unknown> = {}) {
  return {
    id: 'exec-1',
    task_id: 'task-1',
    user_id: 'child-1',
    status: 'ASSIGNED',
    reward_points: 10,
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

  it('shows only AWAITING_CONFIRMATION executions in the pending-confirmation block', async () => {
    const tasks = [task()]
    const executions = [
      execution({ id: 'pending-1', status: 'AWAITING_CONFIRMATION' }),
      execution({ id: 'in-progress-1', status: 'IN_PROGRESS' }),
      execution({ id: 'assigned-1', status: 'ASSIGNED' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, executions)
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
      expect(within(pending).getAllByText(/tidy the room/i).length).toBeGreaterThan(0)
    })
    expect(within(pending).getAllByRole('listitem')).toHaveLength(1)
  })

  it('shows the empty state when there are no pending confirmations', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, [])
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

  it('confirming a pending execution calls the existing transition and refreshes tasks and points', async () => {
    const pendingExecution = execution({ id: 'pending-1', status: 'AWAITING_CONFIRMATION' })
    let executionsCallCount = 0
    let balanceCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
      if (url.endsWith('/api/task-executions')) {
        executionsCallCount += 1
        // After confirmation, the execution is no longer AWAITING_CONFIRMATION.
        const body =
          executionsCallCount === 1 ? [pendingExecution] : [{ ...pendingExecution, status: 'COMPLETED' }]
        return jsonResponse(200, body)
      }
      if (url.endsWith('/api/points/balance')) {
        balanceCallCount += 1
        return jsonResponse(200, { balance: balanceCallCount === 1 ? 0 : 10 })
      }
      if (url.endsWith('/api/users')) {
        return jsonResponse(200, USERS)
      }
      if (url.endsWith('/api/task-executions/pending-1/confirm')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, { ...pendingExecution, status: 'COMPLETED' })
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
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/task-executions')),
    ).toHaveLength(2)
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/points/balance')),
    ).toHaveLength(2)
  })

  it('keeps an execution visible with an error if confirmation fails', async () => {
    const pendingExecution = execution({ id: 'pending-1', status: 'AWAITING_CONFIRMATION' })
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, [pendingExecution])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
        if (url.endsWith('/api/task-executions/pending-1/confirm')) {
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

  it('shows the 5 most recent executions ordered by created_at desc, id desc, read-only', async () => {
    const executions = [
      execution({ id: 'a', task_id: 'task-a', created_at: '2026-09-01T00:00:00Z' }),
      execution({ id: 'b', task_id: 'task-b', created_at: '2026-09-02T00:00:00Z' }),
      execution({ id: 'c', task_id: 'task-c', created_at: '2026-09-03T00:00:00Z' }),
      execution({ id: 'd', task_id: 'task-d', created_at: '2026-09-04T00:00:00Z' }),
      execution({ id: 'e', task_id: 'task-e', created_at: '2026-09-05T00:00:00Z' }),
      execution({ id: 'f', task_id: 'task-f', created_at: '2026-09-06T00:00:00Z' }),
      // Same created_at as "f" -- tie broken by id desc.
      execution({ id: 'g', task_id: 'task-g', created_at: '2026-09-06T00:00:00Z' }),
    ]
    const tasks = [
      task({ id: 'task-a', title: 'Oldest' }),
      task({ id: 'task-b', title: 'Second' }),
      task({ id: 'task-c', title: 'Third' }),
      task({ id: 'task-d', title: 'Fourth' }),
      task({ id: 'task-e', title: 'Fifth' }),
      task({ id: 'task-f', title: 'Newest' }),
      task({ id: 'task-g', title: 'Tied but higher id' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, executions)
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
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, [])
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
        if (url.endsWith('/api/task-executions')) return jsonResponse(200, [])
        if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
        if (url.endsWith('/api/users')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderDashboard()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /create task/i })).toHaveAttribute(
        'href',
        '/tasks/new?from=dashboard',
      )
    })
    expect(screen.getByRole('link', { name: /add user/i })).toHaveAttribute('href', '/users/new')
    expect(screen.getByRole('link', { name: /create reward/i })).toHaveAttribute(
      'href',
      '/rewards/new',
    )
  })

  it('a failed section shows a retry action without hiding successful sections', async () => {
    let executionsCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        if (url.endsWith('/api/task-executions')) {
          executionsCallCount += 1
          if (executionsCallCount === 1) return jsonResponse(500, {})
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
    // Points and Quick Actions remain available despite the executions failure.
    expect(screen.getByText('7')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /create task/i })).toBeInTheDocument()

    const [retryButton] = screen.getAllByRole('button', { name: /retry/i })
    fireEvent.click(retryButton)

    await waitFor(() => {
      expect(screen.getByText(/no tasks waiting for confirmation/i)).toBeInTheDocument()
    })
  })
})
