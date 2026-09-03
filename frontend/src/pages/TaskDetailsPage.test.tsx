import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import TaskDetailsPage from './TaskDetailsPage'

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

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    title: 'Tidy the room',
    description: 'Make it spotless',
    assigned_to: CHILD.id,
    created_by: ADULT.id,
    reward_points: 20,
    status: 'ASSIGNED',
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function baseHandlers(
  url: string,
  currentUser: { id: string; name: string; role: string } = ADULT,
) {
  if (url.endsWith('/api/auth/me')) return jsonResponse(200, currentUser)
  if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
  if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
  return undefined
}

function renderDetails() {
  return render(
    <RouterProvider>
      <TaskDetailsPage />
    </RouterProvider>,
  )
}

beforeEach(() => {
  window.history.pushState({}, '', '/tasks/task-1')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('TaskDetailsPage', () => {
  // --- Loading / fields ------------------------------------------------------

  it('shows a loading state before the task resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderDetails()

    expect(screen.getByText(/loading task/i)).toBeInTheDocument()
  })

  it('displays task fields, human-readable status, creator, and assignee', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Tidy the room' })).toBeInTheDocument()
    })
    expect(screen.getByText('Make it spotless')).toBeInTheDocument()
    expect(screen.getByText(/points: 20/i)).toBeInTheDocument()
    expect(screen.getByText(/status: assigned/i)).toBeInTheDocument()
    expect(screen.queryByText(/^status: ASSIGNED$/)).not.toBeInTheDocument()
    expect(screen.getByText(/assignee: kiddo \(child\)/i)).toBeInTheDocument()
    expect(screen.getByText(/creator: alice \(adult\)/i)).toBeInTheDocument()
  })

  it('shows a load error state with retry, and retry repeats the request', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, task())
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'Tidy the room' })).toBeInTheDocument()
    })
    expect(callCount).toBe(2)
  })

  it('shows a not-found state with a way back for an inaccessible task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) {
          return jsonResponse(404, { error: { code: 'TASK_NOT_FOUND', message: 'Task not found' } })
        }
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/task not found/i)).toBeInTheDocument()
    })
    const backLinks = screen.getAllByRole('link', { name: /back to tasks/i })
    expect(backLinks.length).toBeGreaterThan(0)
    for (const link of backLinks) {
      expect(link).toHaveAttribute('href', '/tasks')
    }
  })

  // --- Role/status action matrix -----------------------------------------------

  it('creator sees Edit/Reassign/Cancel when ASSIGNED', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /^edit$/i })).toHaveAttribute(
        'href',
        '/tasks/task-1/edit',
      )
    })
    expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
  })

  it('creator sees only Cancel when IN_PROGRESS', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'IN_PROGRESS' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^reassign$/i })).not.toBeInTheDocument()
  })

  it('creator sees Confirm and Cancel when AWAITING_CONFIRMATION', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'AWAITING_CONFIRMATION' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
  })

  it('creator sees no mutation actions for terminal states', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'COMPLETED' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/status: completed/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
  })

  it('assignee sees Start in ASSIGNED', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })
  })

  it('assignee sees Mark ready in IN_PROGRESS', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'IN_PROGRESS' }))
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
    })
  })

  it('assignee does not see Confirm, Edit, Reassign, or Cancel', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'AWAITING_CONFIRMATION' }))
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/status: awaiting confirmation/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^reassign$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /cancel task/i })).not.toBeInTheDocument()
  })

  // --- Lifecycle mutations -----------------------------------------------------

  it('Confirm calls the API, refreshes the task, and refreshes points balance', async () => {
    let taskCallCount = 0
    let balanceCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1')) {
        taskCallCount += 1
        const status = taskCallCount === 1 ? 'AWAITING_CONFIRMATION' : 'COMPLETED'
        return jsonResponse(200, task({ status }))
      }
      if (url.endsWith('/api/tasks/task-1/confirm')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, task({ status: 'COMPLETED' }))
      }
      if (url.endsWith('/api/points/balance')) {
        balanceCallCount += 1
        return jsonResponse(200, { balance: 0 })
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^confirm$/i }))

    await waitFor(() => {
      expect(screen.getByText(/status: completed/i)).toBeInTheDocument()
    })
    expect(taskCallCount).toBe(2)
    expect(balanceCallCount).toBe(1)
  })

  // --- Reassign ------------------------------------------------------------------

  it('the assignee selector uses the existing users list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^reassign$/i }))

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /bob \(adult\)/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('option', { name: /kiddo \(child\)/i })).toBeInTheDocument()
  })

  it('successful reassignment refreshes the task and shows the new assignee', async () => {
    let taskCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1')) {
        taskCallCount += 1
        const assignedTo = taskCallCount === 1 ? CHILD.id : OTHER_ADULT.id
        return jsonResponse(200, task({ status: 'ASSIGNED', assigned_to: assignedTo }))
      }
      if (url.endsWith('/api/tasks/task-1/reassign')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(init?.body as string)).toEqual({ assigned_to: OTHER_ADULT.id })
        return jsonResponse(200, task({ status: 'ASSIGNED', assigned_to: OTHER_ADULT.id }))
      }
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^reassign$/i }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /bob \(adult\)/i })).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText(/new assignee/i), { target: { value: OTHER_ADULT.id } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByText(/assignee: bob \(adult\)/i)).toBeInTheDocument()
    })
    expect(taskCallCount).toBe(2)
  })

  it('reassignment errors are displayed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
        if (url.endsWith('/api/tasks/task-1/reassign')) {
          return jsonResponse(422, {
            error: { code: 'ASSIGNEE_NOT_FOUND', message: 'Assignee not found' },
          })
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^reassign$/i }))
    await waitFor(() => {
      expect(screen.getByRole('option', { name: /bob \(adult\)/i })).toBeInTheDocument()
    })
    fireEvent.change(screen.getByLabelText(/new assignee/i), { target: { value: OTHER_ADULT.id } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByText('Assignee not found')).toBeInTheDocument()
    })
  })

  it('Reassign is unavailable outside ASSIGNED', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1'))
          return jsonResponse(200, task({ status: 'IN_PROGRESS' }))
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^reassign$/i })).not.toBeInTheDocument()
  })

  // --- Cancel --------------------------------------------------------------------

  it('Cancel requires explicit confirmation before calling the API', async () => {
    const fetchMock = vi.fn((url: string) => {
      if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
      return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /cancel task/i }))

    expect(screen.getByText(/cancel "tidy the room"/i)).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/cancel')),
    ).toHaveLength(0)
  })

  it('confirming makes the correct API call and is disabled while pending', async () => {
    let resolveCancel: () => void = () => {}
    let taskCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1')) {
          taskCallCount += 1
          const status = taskCallCount === 1 ? 'ASSIGNED' : 'CANCELLED'
          return jsonResponse(200, task({ status }))
        }
        if (url.endsWith('/api/tasks/task-1/cancel')) {
          expect(init?.method).toBe('POST')
          return new Promise((resolve) => {
            resolveCancel = () =>
              resolve({ ok: true, status: 200, json: () => Promise.resolve(task({ status: 'CANCELLED' })) })
          })
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /cancel task/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancelling|cancel task/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancelling/i })).toBeDisabled()
    })
    expect(screen.getByRole('button', { name: /keep task/i })).toBeDisabled()

    resolveCancel()
    await waitFor(() => {
      expect(screen.getByText(/status: cancelled/i)).toBeInTheDocument()
    })
  })

  it('cancellation errors are displayed and the task remains as-is', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ status: 'ASSIGNED' }))
        if (url.endsWith('/api/tasks/task-1/cancel')) {
          return jsonResponse(409, {
            error: { code: 'INVALID_TRANSITION', message: 'Cannot cancel this task' },
          })
        }
        return baseHandlers(url, ADULT) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /cancel task/i }))
    fireEvent.click(screen.getByRole('button', { name: /cancelling|cancel task/i }))

    await waitFor(() => {
      expect(screen.getByText('Cannot cancel this task')).toBeInTheDocument()
    })
    expect(screen.getByText(/status: assigned/i)).toBeInTheDocument()
  })
})
