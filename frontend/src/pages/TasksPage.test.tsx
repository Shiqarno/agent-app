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
const CHILD = { id: 'child-1', name: 'Kiddo', role: 'child' }

function task(
  overrides: Partial<{
    id: string
    title: string
    description: string | null
    reward_points: number
    is_active: boolean
    created_by: string
    created_at: string
    updated_at: string
  }> = {},
) {
  return {
    id: 'task-1',
    title: 'Tidy the room',
    description: null,
    reward_points: 10,
    is_active: true,
    created_by: ADULT.id,
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function execution(
  overrides: Partial<{
    id: string
    task_id: string
    user_id: string
    status: string
    reward_points: number
    created_at: string
    updated_at: string
  }> = {},
) {
  return {
    id: 'exec-1',
    task_id: 'task-1',
    user_id: CHILD.id,
    status: 'ASSIGNED',
    reward_points: 10,
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

// A default stub covering /api/auth/me and /api/task-executions, which
// every render of TasksPage requests regardless of the scenario under test.
function baseHandlers(
  url: string,
  currentUser: { id: string; name: string; role: string } = ADULT,
  executions: Record<string, unknown>[] = [],
) {
  if (url.endsWith('/api/auth/me')) return jsonResponse(200, currentUser)
  if (url.endsWith('/api/task-executions')) return jsonResponse(200, executions)
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

  // --- Adult: Task definitions --------------------------------------------

  describe('Adult', () => {
    it('renders the loaded task definitions', async () => {
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
      expect(screen.getByText(/reward points: 10/i)).toBeInTheDocument()
      const card = screen.getByText('Tidy the room').closest('li') as HTMLElement
      expect(within(card).getByText(/^active$/i)).toBeInTheDocument()
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

    it('filters client-side by active status without triggering additional /api/tasks requests', async () => {
      const tasks = [
        task({ id: 'a', title: 'Active task', is_active: true }),
        task({ id: 'b', title: 'Inactive task', is_active: false }),
      ]
      const fetchMock = vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, tasks)
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getAllByRole('listitem')).toHaveLength(2)
      })
      const tasksCallsBefore = fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith('/api/tasks'),
      ).length

      fireEvent.click(screen.getByRole('button', { name: 'Active' }))
      await waitFor(() => {
        expect(screen.getAllByRole('listitem')).toHaveLength(1)
      })
      expect(screen.getByText('Active task')).toBeInTheDocument()

      fireEvent.click(screen.getByRole('button', { name: 'Inactive' }))
      await waitFor(() => {
        expect(screen.getByText('Inactive task')).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: 'All' }))
      await waitFor(() => {
        expect(screen.getAllByRole('listitem')).toHaveLength(2)
      })

      const tasksCallsAfter = fetchMock.mock.calls.filter(([url]) =>
        String(url).endsWith('/api/tasks'),
      ).length
      expect(tasksCallsAfter).toBe(tasksCallsBefore)
    })

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

    it('each task card exposes a Details link to /tasks/:id, with no inline lifecycle actions', async () => {
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
      const item = screen.getByText('Tidy the room').closest('li') as HTMLElement
      expect(within(item).queryByRole('button')).not.toBeInTheDocument()
    })
  })

  // --- Child: My Tasks / Available Tasks ----------------------------------

  describe('Child', () => {
    it('lists claimed executions under My Tasks with the task title resolved', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'ASSIGNED' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /my tasks/i })).toBeInTheDocument()
      })
      expect(screen.getByText('Tidy the room')).toBeInTheDocument()
      expect(screen.getByText(/status: assigned/i)).toBeInTheDocument()
    })

    it('lists active unclaimed tasks under Available Tasks with a Claim button', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) {
            return jsonResponse(200, [
              task({ id: 'available', title: 'Available task', is_active: true }),
            ])
          }
          return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /available tasks/i })).toBeInTheDocument()
      })
      expect(screen.getByText('Available task')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /^claim$/i })).toBeInTheDocument()
    })

    it('a claimed task does not also appear under Available Tasks', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'ASSIGNED' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByText(/no tasks available to claim/i)).toBeInTheDocument()
      })
    })

    it('an inactive, unclaimed task does not appear under Available Tasks', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task({ is_active: false })])
          return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByText(/no tasks available to claim/i)).toBeInTheDocument()
      })
    })

    it('shows Start only for an ASSIGNED execution', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'ASSIGNED' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
      })
    })

    it('shows Mark ready only for an IN_PROGRESS execution', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'IN_PROGRESS' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
      })
    })

    it('a Child never sees Confirm, and sees a status instead once AWAITING_CONFIRMATION', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'AWAITING_CONFIRMATION' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByText(/status: awaiting confirmation/i)).toBeInTheDocument()
      })
      expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument()
    })

    it('completed executions have no lifecycle action', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
          return (
            baseHandlers(url, CHILD, [execution({ status: 'COMPLETED' })]) ??
            Promise.reject(new Error(`Unexpected request: ${url}`))
          )
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByText('Tidy the room')).toBeInTheDocument()
      })
      const item = screen.getByText('Tidy the room').closest('li') as HTMLElement
      expect(within(item).queryByRole('button')).not.toBeInTheDocument()
    })

    it('a Child sees no Create task action anywhere on the page', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn((url: string) => {
          if (url.endsWith('/api/tasks')) return jsonResponse(200, [])
          return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
        }),
      )

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('heading', { name: /my tasks/i })).toBeInTheDocument()
      })
      expect(screen.queryByRole('link', { name: /create.*task/i })).not.toBeInTheDocument()
    })

    // --- Mutation success ------------------------------------------------------

    it('Start reloads on success', async () => {
      let executionsCallCount = 0
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) {
          executionsCallCount += 1
          const status = executionsCallCount === 1 ? 'ASSIGNED' : 'IN_PROGRESS'
          return jsonResponse(200, [execution({ status })])
        }
        if (url.endsWith('/api/task-executions/exec-1/start')) {
          expect(init?.method).toBe('POST')
          return jsonResponse(200, execution({ status: 'IN_PROGRESS' }))
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /^start$/i }))

      await waitFor(() => {
        expect(screen.getByText(/status: in progress/i)).toBeInTheDocument()
      })
      expect(executionsCallCount).toBe(2)
    })

    it('Mark ready reloads on success', async () => {
      let executionsCallCount = 0
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) {
          executionsCallCount += 1
          const status = executionsCallCount === 1 ? 'IN_PROGRESS' : 'AWAITING_CONFIRMATION'
          return jsonResponse(200, [execution({ status })])
        }
        if (url.endsWith('/api/task-executions/exec-1/ready')) {
          expect(init?.method).toBe('POST')
          return jsonResponse(200, execution({ status: 'AWAITING_CONFIRMATION' }))
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /mark ready/i }))

      await waitFor(() => {
        expect(screen.getByText(/status: awaiting confirmation/i)).toBeInTheDocument()
      })
      expect(executionsCallCount).toBe(2)
    })

    it('Claim reloads My Tasks and Available Tasks on success', async () => {
      let executionsCallCount = 0
      const fetchMock = vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) {
          executionsCallCount += 1
          if (executionsCallCount === 1) return jsonResponse(200, [])
          return jsonResponse(200, [execution({ status: 'ASSIGNED' })])
        }
        if (url.endsWith('/api/tasks/task-1/claim')) {
          expect(init?.method).toBe('POST')
          return jsonResponse(201, execution({ status: 'ASSIGNED' }))
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
      })
      vi.stubGlobal('fetch', fetchMock)

      renderTasksPage()

      await waitFor(() => {
        expect(screen.getByRole('button', { name: /^claim$/i })).toBeInTheDocument()
      })

      fireEvent.click(screen.getByRole('button', { name: /^claim$/i }))

      await waitFor(() => {
        expect(screen.getByText(/no tasks available to claim/i)).toBeInTheDocument()
      })
      expect(screen.getByText(/status: assigned/i)).toBeInTheDocument()
    })

    it('disables the action button while the mutation is in flight', async () => {
      let resolveStart: () => void = () => {}
      let executionsCallCount = 0
      const fetchMock = vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) {
          executionsCallCount += 1
          const status = executionsCallCount === 1 ? 'ASSIGNED' : 'IN_PROGRESS'
          return jsonResponse(200, [execution({ status })])
        }
        if (url.endsWith('/api/task-executions/exec-1/start')) {
          return new Promise((resolve) => {
            resolveStart = () =>
              resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve(execution({ status: 'IN_PROGRESS' })),
              })
          })
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
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
        expect(screen.getByText(/status: in progress/i)).toBeInTheDocument()
      })
    })

    // --- Mutation failure --------------------------------------------------------

    it('keeps the execution state unchanged and shows a recoverable error on mutation failure', async () => {
      const fetchMock = vi.fn((url: string) => {
        if (url.endsWith('/api/tasks')) return jsonResponse(200, [task()])
        if (url.endsWith('/api/task-executions')) {
          return jsonResponse(200, [execution({ status: 'ASSIGNED' })])
        }
        if (url.endsWith('/api/task-executions/exec-1/start')) {
          return jsonResponse(409, {
            error: { code: 'INVALID_TRANSITION', message: 'Cannot start this task' },
          })
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected request: ${url}`))
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
      expect(screen.getByText(/status: assigned/i)).toBeInTheDocument()
      expect(screen.getByRole('button', { name: /^start$/i })).toBeEnabled()
    })
  })
})
