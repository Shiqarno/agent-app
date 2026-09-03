import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import TasksPage from './TasksPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const ADULT = { id: 'adult-1', name: 'Alice', role: 'adult' }
const OTHER_ADULT = { id: 'adult-2', name: 'Bob', role: 'adult' }
const CHILD = { id: 'child-1', name: 'Kiddo', role: 'child' }
const USERS = [ADULT, OTHER_ADULT, CHILD]

function task(overrides: Partial<{
  id: string
  title: string
  description: string | null
  assigned_to: string
  created_by: string
  reward_points: number
  status: string
  created_at: string
  updated_at: string
}> = {}) {
  return {
    id: 'task-1',
    title: 'Tidy the room',
    description: null,
    assigned_to: CHILD.id,
    created_by: ADULT.id,
    reward_points: 10,
    status: 'ASSIGNED',
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function renderTasksPage() {
  return render(
    <RouterProvider>
      <TasksPage />
    </RouterProvider>,
  )
}

// A default stub covering /api/auth/me and /api/users, which every render
// of TasksPage requests regardless of the scenario under test.
function baseHandlers(url: string, currentUser: { id: string; name: string; role: string } = ADULT) {
  if (url.endsWith('/api/auth/me')) return jsonResponse(200, currentUser)
  if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
  return undefined
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('TasksPage', () => {
  // --- Loading -----------------------------------------------------------

  it('shows an explicit loading state before the task list resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderTasksPage()

    expect(screen.getByText(/loading tasks/i)).toBeInTheDocument()
    expect(screen.queryByText(/no tasks yet/i)).not.toBeInTheDocument()
  })

  it('renders the loaded task list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText('Tidy the room')).toBeInTheDocument()
    })
    expect(screen.getByText(/points: 10/i)).toBeInTheDocument()
    expect(screen.getByText(/status: ASSIGNED/i)).toBeInTheDocument()
  })

  it('shows the empty state with a path to create the first task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText(/no tasks yet/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /create your first task/i })).toHaveAttribute(
      'href',
      '/tasks/new?from=tasks',
    )
  })

  it('shows an error state with retry when loading fails, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, [task()])
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByText('Tidy the room')).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  it('shows a useful fallback message on a genuine network failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return Promise.reject('network down')
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText(/couldn't load tasks/i)).toBeInTheDocument()
    })
  })

  // --- Sorting -------------------------------------------------------------

  it('sorts tasks by created_at desc, id desc (tie-break on equal created_at)', async () => {
    const tasks = [
      task({ id: 'a', title: 'Oldest', created_at: '2026-09-01T00:00:00Z' }),
      task({ id: 'c', title: 'Tied high id', created_at: '2026-09-02T00:00:00Z' }),
      task({ id: 'b', title: 'Tied low id', created_at: '2026-09-02T00:00:00Z' }),
      task({ id: 'z', title: 'Newest', created_at: '2026-09-03T00:00:00Z' }),
    ]
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(4)
    })
    const titles = screen.getAllByRole('listitem').map((item) => item.textContent)
    expect(titles[0]).toMatch(/newest/i)
    expect(titles[1]).toMatch(/tied high id/i)
    expect(titles[2]).toMatch(/tied low id/i)
    expect(titles[3]).toMatch(/oldest/i)
  })

  // --- Filtering -------------------------------------------------------------

  it('filters client-side without triggering additional /api/tasks requests', async () => {
    const tasks = [
      task({ id: 'a', title: 'Assigned task', status: 'ASSIGNED' }),
      task({ id: 'b', title: 'In progress task', status: 'IN_PROGRESS' }),
      task({ id: 'c', title: 'Awaiting task', status: 'AWAITING_CONFIRMATION' }),
      task({ id: 'd', title: 'Completed task', status: 'COMPLETED' }),
    ]
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
      return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(4)
    })
    const tasksCallsBefore = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith('/api/tasks'),
    ).length

    fireEvent.click(screen.getByRole('button', { name: 'Assigned' }))
    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(1)
    })
    expect(screen.getByText('Assigned task')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'In progress' }))
    await waitFor(() => {
      expect(screen.getByText('In progress task')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Awaiting confirmation' }))
    await waitFor(() => {
      expect(screen.getByText('Awaiting task')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'Completed' }))
    await waitFor(() => {
      expect(screen.getByText('Completed task')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: 'All' }))
    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(4)
    })

    const tasksCallsAfter = fetchMock.mock.calls.filter(([url]) =>
      String(url).endsWith('/api/tasks'),
    ).length
    expect(tasksCallsAfter).toBe(tasksCallsBefore)
  })

  // --- Lifecycle action visibility --------------------------------------------

  it('shows Start only to the assignee of an ASSIGNED task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [task({ status: 'ASSIGNED', assigned_to: OTHER_ADULT.id })])
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText('Tidy the room')).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^start$/i })).not.toBeInTheDocument()
  })

  it('shows Mark ready only to the assignee of an IN_PROGRESS task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [
            task({ id: 'mine', status: 'IN_PROGRESS', assigned_to: ADULT.id }),
            task({ id: 'not-mine', status: 'IN_PROGRESS', assigned_to: OTHER_ADULT.id }),
          ])
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(2)
    })
    expect(screen.getAllByRole('button', { name: /mark ready/i })).toHaveLength(1)
  })

  it('shows Confirm only to the creator of an AWAITING_CONFIRMATION task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [
            task({ id: 'mine', status: 'AWAITING_CONFIRMATION', created_by: ADULT.id }),
            task({ id: 'not-mine', status: 'AWAITING_CONFIRMATION', created_by: OTHER_ADULT.id }),
          ])
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getAllByRole('listitem')).toHaveLength(2)
    })
    expect(screen.getAllByRole('button', { name: /^confirm$/i })).toHaveLength(1)
  })

  it('completed tasks have no lifecycle action', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [
            task({ status: 'COMPLETED', assigned_to: ADULT.id, created_by: ADULT.id }),
          ])
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText('Tidy the room')).toBeInTheDocument()
    })
    const item = screen.getByText('Tidy the room').closest('li') as HTMLElement
    expect(within(item).queryByRole('button')).not.toBeInTheDocument()
  })

  // --- Child role (Issue #15) -------------------------------------------------

  it('a Child sees Start on their own ASSIGNED task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [task({ status: 'ASSIGNED', assigned_to: CHILD.id })])
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })
  })

  it('a Child sees Mark ready on their own IN_PROGRESS task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [task({ status: 'IN_PROGRESS', assigned_to: CHILD.id })])
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
    })
  })

  it('a Child never sees Confirm, even on an AWAITING_CONFIRMATION task, and sees a status instead', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          // created_by set to the Child's own id: structurally this can never
          // happen for real (task creation is Adult-only), but the rule is
          // asserted explicitly (Issue #15 §8), so prove it holds even here.
          return jsonResponse(200, [
            task({ status: 'AWAITING_CONFIRMATION', assigned_to: CHILD.id, created_by: CHILD.id }),
          ])
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText(/status: Awaiting confirmation/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument()
  })

  it('a Child sees no action and no Create task button anywhere on the page', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) {
          return jsonResponse(200, [
            task({ status: 'COMPLETED', assigned_to: CHILD.id, created_by: ADULT.id }),
          ])
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText(/status: Completed/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: /create task/i })).not.toBeInTheDocument()
  })

  it('a Child sees no Create task action on the empty state either', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByText(/no tasks yet/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: /create.*task/i })).not.toBeInTheDocument()
  })

  // --- Mutation success ------------------------------------------------------

  it('Start reloads the task list on success', async () => {
    let tasksCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks')) {
        tasksCallCount += 1
        const status = tasksCallCount === 1 ? 'ASSIGNED' : 'IN_PROGRESS'
        return jsonResponse(200, [task({ status, assigned_to: ADULT.id })])
      }
      if (url.endsWith('/api/tasks/task-1/start')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, task({ status: 'IN_PROGRESS', assigned_to: ADULT.id }))
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /^start$/i }))

    await waitFor(() => {
      expect(screen.getByText(/status: In progress/i)).toBeInTheDocument()
    })
    expect(tasksCallCount).toBe(2)
  })

  it('Mark ready reloads the task list on success', async () => {
    let tasksCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks')) {
        tasksCallCount += 1
        const status = tasksCallCount === 1 ? 'IN_PROGRESS' : 'AWAITING_CONFIRMATION'
        return jsonResponse(200, [task({ status, assigned_to: ADULT.id })])
      }
      if (url.endsWith('/api/tasks/task-1/ready')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, task({ status: 'AWAITING_CONFIRMATION', assigned_to: ADULT.id }))
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /mark ready/i }))

    await waitFor(() => {
      expect(screen.getByText(/status: Awaiting confirmation/i)).toBeInTheDocument()
    })
    expect(tasksCallCount).toBe(2)
  })

  it('Confirm reloads the task list and the point balance on success', async () => {
    let tasksCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks')) {
        tasksCallCount += 1
        const status = tasksCallCount === 1 ? 'AWAITING_CONFIRMATION' : 'COMPLETED'
        return jsonResponse(200, [task({ status, created_by: ADULT.id })])
      }
      if (url.endsWith('/api/tasks/task-1/confirm')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, task({ status: 'COMPLETED', created_by: ADULT.id }))
      }
      if (url.endsWith('/api/points/balance')) {
        return jsonResponse(200, { balance: 10 })
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => {
      expect(screen.getByText(/status: COMPLETED/i)).toBeInTheDocument()
    })
    expect(tasksCallCount).toBe(2)
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/api/points/balance')),
    ).toHaveLength(1)
  })

  it('disables the action button while the mutation is in flight', async () => {
    let resolveStart: () => void = () => {}
    let tasksCallCount = 0
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/tasks')) {
        tasksCallCount += 1
        const status = tasksCallCount === 1 ? 'ASSIGNED' : 'IN_PROGRESS'
        return jsonResponse(200, [task({ status, assigned_to: ADULT.id })])
      }
      if (url.endsWith('/api/tasks/task-1/start')) {
        return new Promise((resolve) => {
          resolveStart = () =>
            resolve({
              ok: true,
              status: 200,
              json: () => Promise.resolve(task({ status: 'IN_PROGRESS', assigned_to: ADULT.id })),
            })
        })
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /^start$/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /starting/i })).toBeDisabled()
    })

    resolveStart()

    await waitFor(() => {
      expect(screen.getByText(/status: In progress/i)).toBeInTheDocument()
    })
  })

  // --- Mutation failure --------------------------------------------------------

  it('keeps the task state unchanged and shows a recoverable error on mutation failure', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/tasks')) {
        return jsonResponse(200, [task({ status: 'ASSIGNED', assigned_to: ADULT.id })])
      }
      if (url.endsWith('/api/tasks/task-1/start')) {
        return jsonResponse(409, {
          error: { code: 'INVALID_TRANSITION', message: 'Cannot start this task' },
        })
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /^start$/i }))

    await waitFor(() => {
      expect(screen.getByText('Cannot start this task')).toBeInTheDocument()
    })
    // State is unchanged -- still ASSIGNED, Start button still present (retry).
    expect(screen.getByText(/status: ASSIGNED/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^start$/i })).toBeEnabled()
  })

  // --- Creation ------------------------------------------------------------

  it('exposes a Create task action pointing at the existing /tasks/new flow', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /\+ create task/i })).toHaveAttribute(
        'href',
        '/tasks/new?from=tasks',
      )
    })
  })

  it('each task card exposes a Details link to /tasks/:id', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task({ id: 'task-42' })])
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      }),
    )

    renderTasksPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /details/i })).toHaveAttribute(
        'href',
        '/tasks/task-42',
      )
    })
  })
})
