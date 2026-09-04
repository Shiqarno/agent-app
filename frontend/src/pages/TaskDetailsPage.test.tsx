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
const OTHER_CHILD = { id: 'child-2', name: 'Junior', role: 'child' }
const USERS = [ADULT, OTHER_ADULT, CHILD, OTHER_CHILD]

function task(overrides: Record<string, unknown> = {}) {
  return {
    id: 'task-1',
    title: 'Tidy the room',
    description: 'Make it spotless',
    reward_points: 20,
    is_active: true,
    created_by: ADULT.id,
    created_at: '2026-09-03T10:00:00Z',
    updated_at: '2026-09-03T10:00:00Z',
    ...overrides,
  }
}

function execution(overrides: Record<string, unknown> = {}) {
  return {
    id: 'exec-1',
    task_id: 'task-1',
    user_id: CHILD.id,
    status: 'ASSIGNED',
    reward_points: 20,
    created_at: '2026-09-03T11:00:00Z',
    updated_at: '2026-09-03T11:00:00Z',
    ...overrides,
  }
}

function baseHandlers(
  url: string,
  currentUser: { id: string; name: string; role: string } = ADULT,
  executions: Record<string, unknown>[] = [],
) {
  if (url.endsWith('/api/auth/me')) return jsonResponse(200, currentUser)
  if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
  if (url.endsWith('/api/points/balance')) return jsonResponse(200, { balance: 0 })
  if (url.endsWith('/api/task-executions')) return jsonResponse(200, executions)
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

  it('displays task definition fields, active badge, and creator', async () => {
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
    expect(screen.getByText(/reward points: 20/i)).toBeInTheDocument()
    expect(screen.getByText(/^available for claim$/i)).toBeInTheDocument()
    expect(screen.getByText(/creator: alice \(adult\)/i)).toBeInTheDocument()
  })

  it('displays a not-available status for a deactivated task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ is_active: false }))
        return baseHandlers(url) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/^not currently available for claim$/i)).toBeInTheDocument()
    })
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

  // --- Creator: execution list ---------------------------------------------------

  it('creator sees an Edit link and "no one has claimed" when there are no executions', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return baseHandlers(url, ADULT, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /^edit$/i })).toHaveAttribute(
        'href',
        '/tasks/task-1/edit',
      )
    })
    expect(screen.getByText(/no one has claimed this task yet/i)).toBeInTheDocument()
  })

  it('creator sees no Activate button on an active task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return baseHandlers(url, ADULT, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/^available for claim$/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^activate$/i })).not.toBeInTheDocument()
  })

  it('creator can activate an inactive task; the button is disabled while pending and there is no optimistic update', async () => {
    let resolveActivate: (value: unknown) => void = () => {}
    let taskCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
          taskCallCount += 1
          return jsonResponse(200, task({ is_active: taskCallCount > 1 }))
        }
        if (url.endsWith('/api/tasks/task-1/activate')) {
          expect(init?.method).toBe('POST')
          return new Promise((resolve) => {
            resolveActivate = resolve
          }).then(() => jsonResponse(200, task({ is_active: true })))
        }
        return baseHandlers(url, ADULT, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^activate$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^activate$/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /activating/i })).toBeDisabled()
    })
    // Still shows the pre-activation status -- the page never flips
    // is_active locally before the request resolves.
    expect(screen.getByText(/^not currently available for claim$/i)).toBeInTheDocument()
    expect(taskCallCount).toBe(1)

    resolveActivate(undefined)

    await waitFor(() => {
      expect(screen.getByText(/^available for claim$/i)).toBeInTheDocument()
    })
    expect(taskCallCount).toBe(2)
  })

  it('activation errors are displayed and the task remains inactive', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse(200, task({ is_active: false }))
        }
        if (url.endsWith('/api/tasks/task-1/activate')) {
          return jsonResponse(403, { error: { code: 'FORBIDDEN', message: 'You do not own this task' } })
        }
        return baseHandlers(url, ADULT, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^activate$/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /^activate$/i }))

    await waitFor(() => {
      expect(screen.getByText('You do not own this task')).toBeInTheDocument()
    })
    expect(screen.getByText(/^not currently available for claim$/i)).toBeInTheDocument()
  })

  it('creator sees Reassign and Cancel task on an ASSIGNED execution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'ASSIGNED' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument()
    expect(screen.getByText(/assignee: kiddo \(child\)/i)).toBeInTheDocument()
  })

  it('creator sees only Cancel task on an IN_PROGRESS execution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'IN_PROGRESS' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /^reassign$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^confirm$/i })).not.toBeInTheDocument()
  })

  it('creator sees Confirm and Cancel task on an AWAITING_CONFIRMATION execution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'AWAITING_CONFIRMATION' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^confirm$/i })).toBeInTheDocument()
    })
    expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
  })

  it('creator sees no mutation actions for a COMPLETED or CANCELLED execution', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'COMPLETED' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/status: completed/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('creator sees multiple independent executions of the same task', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [
            execution({ id: 'exec-1', user_id: CHILD.id, status: 'COMPLETED' }),
            execution({ id: 'exec-2', user_id: OTHER_CHILD.id, status: 'ASSIGNED' }),
          ]) ?? Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/assignee: kiddo \(child\)/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/assignee: junior \(child\)/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^reassign$/i })).toBeInTheDocument()
  })

  // --- Confirm ---------------------------------------------------------------

  it('Confirm calls the API, refreshes the execution list, and refreshes points balance', async () => {
    let executionCallCount = 0
    let balanceCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
      if (url.endsWith('/api/task-executions')) {
        executionCallCount += 1
        const status = executionCallCount === 1 ? 'AWAITING_CONFIRMATION' : 'COMPLETED'
        return jsonResponse(200, [execution({ status })])
      }
      if (url.endsWith('/api/task-executions/exec-1/confirm')) {
        expect(init?.method).toBe('POST')
        return jsonResponse(200, execution({ status: 'COMPLETED' }))
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
    expect(executionCallCount).toBe(2)
    expect(balanceCallCount).toBe(1)
  })

  // --- Reassign ------------------------------------------------------------------

  it('the assignee selector uses the existing users list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'ASSIGNED' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
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

  it('successful reassignment refreshes the execution and shows the new assignee', async () => {
    let executionCallCount = 0
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
      if (url.endsWith('/api/task-executions')) {
        executionCallCount += 1
        const userId = executionCallCount === 1 ? CHILD.id : OTHER_ADULT.id
        return jsonResponse(200, [execution({ status: 'ASSIGNED', user_id: userId })])
      }
      if (url.endsWith('/api/task-executions/exec-1/reassign')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(init?.body as string)).toEqual({ assigned_to: OTHER_ADULT.id })
        return jsonResponse(200, execution({ status: 'ASSIGNED', user_id: OTHER_ADULT.id }))
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
    expect(executionCallCount).toBe(2)
  })

  it('reassignment errors are displayed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        if (url.endsWith('/api/task-executions/exec-1/reassign')) {
          return jsonResponse(422, {
            error: { code: 'ASSIGNEE_NOT_FOUND', message: 'Assignee not found' },
          })
        }
        return (
          baseHandlers(url, ADULT, [execution({ status: 'ASSIGNED' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
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
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, ADULT, [execution({ status: 'IN_PROGRESS' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
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
      if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
      return (
        baseHandlers(url, ADULT, [execution({ status: 'ASSIGNED' })]) ??
        Promise.reject(new Error(`Unexpected: ${url}`))
      )
    })
    vi.stubGlobal('fetch', fetchMock)

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /cancel task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /cancel task/i }))

    expect(screen.getByText(/cancel this execution/i)).toBeInTheDocument()
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith('/cancel')),
    ).toHaveLength(0)
  })

  it('confirming makes the correct API call and is disabled while pending', async () => {
    let resolveCancel: (value: unknown) => void = () => {}
    let executionCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        if (url.endsWith('/api/task-executions')) {
          executionCallCount += 1
          const status = executionCallCount === 1 ? 'ASSIGNED' : 'CANCELLED'
          return jsonResponse(200, [execution({ status })])
        }
        if (url.endsWith('/api/task-executions/exec-1/cancel')) {
          expect(init?.method).toBe('POST')
          return new Promise((resolve) => {
            resolveCancel = resolve
          }).then(() => jsonResponse(200, execution({ status: 'CANCELLED' })))
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

    resolveCancel(undefined)
    await waitFor(() => {
      expect(screen.getByText(/status: cancelled/i)).toBeInTheDocument()
    })
  })

  it('cancellation errors are displayed and the execution remains as-is', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        if (url.endsWith('/api/task-executions/exec-1/cancel')) {
          return jsonResponse(409, {
            error: { code: 'INVALID_TRANSITION', message: 'Cannot cancel this task' },
          })
        }
        return (
          baseHandlers(url, ADULT, [execution({ status: 'ASSIGNED' })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
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

  // --- Child: own execution / claim -------------------------------------------

  it('Child with their own ASSIGNED execution sees Start, not Claim', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, CHILD, [execution({ status: 'ASSIGNED', user_id: CHILD.id })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /claim task/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
  })

  it('Child with their own IN_PROGRESS execution sees Mark ready', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, CHILD, [execution({ status: 'IN_PROGRESS', user_id: CHILD.id })]) ??
          Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /mark ready/i })).toBeInTheDocument()
    })
  })

  it('Child with an AWAITING_CONFIRMATION execution sees status only, no action', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, CHILD, [
            execution({ status: 'AWAITING_CONFIRMATION', user_id: CHILD.id }),
          ]) ?? Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/your status: awaiting confirmation/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('Child never sees the creator execution list or Edit', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        return (
          baseHandlers(url, CHILD, [
            execution({ id: 'exec-1', status: 'ASSIGNED', user_id: CHILD.id }),
            execution({ id: 'exec-2', status: 'ASSIGNED', user_id: OTHER_CHILD.id }),
          ]) ?? Promise.reject(new Error(`Unexpected: ${url}`))
        )
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })
    expect(screen.queryByText(/junior/i)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /^edit$/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^reassign$/i })).not.toBeInTheDocument()
  })

  it('Child with no execution on an active task sees a Claim button', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ is_active: true }))
        return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /claim task/i })).toBeInTheDocument()
    })
  })

  it('Child with no execution on an inactive task sees no Claim button', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task({ is_active: false }))
        return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByText(/^not currently available$/i)).toBeInTheDocument()
    })
    expect(screen.queryByRole('button', { name: /claim task/i })).not.toBeInTheDocument()
  })

  it('Claiming calls the API and refreshes into the new execution state', async () => {
    let executionCallCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        if (url.endsWith('/api/task-executions')) {
          executionCallCount += 1
          if (executionCallCount === 1) return jsonResponse(200, [])
          return jsonResponse(200, [execution({ status: 'ASSIGNED', user_id: CHILD.id })])
        }
        if (url.endsWith('/api/tasks/task-1/claim')) {
          expect(init?.method).toBe('POST')
          return jsonResponse(201, execution({ status: 'ASSIGNED', user_id: CHILD.id }))
        }
        return baseHandlers(url, CHILD) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /claim task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /claim task/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^start$/i })).toBeInTheDocument()
    })
  })

  it('claim errors are displayed', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, task())
        if (url.endsWith('/api/tasks/task-1/claim')) {
          return jsonResponse(409, {
            error: { code: 'TASK_ALREADY_CLAIMED', message: 'You already claimed this task' },
          })
        }
        return baseHandlers(url, CHILD, []) ?? Promise.reject(new Error(`Unexpected: ${url}`))
      }),
    )

    renderDetails()

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /claim task/i })).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /claim task/i }))

    await waitFor(() => {
      expect(screen.getByText('You already claimed this task')).toBeInTheDocument()
    })
  })
})
