import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import EditTaskPage from './EditTaskPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const EXISTING_TASK = {
  id: 'task-1',
  title: 'Tidy the room',
  description: 'Make it spotless',
  reward_points: 20,
  is_active: true,
  created_by: 'adult-1',
  created_at: '2026-09-03T10:00:00Z',
  updated_at: '2026-09-03T10:00:00Z',
}

function renderPage() {
  return render(
    <RouterProvider>
      <EditTaskPage />
    </RouterProvider>,
  )
}

beforeEach(() => {
  window.history.pushState({}, '', '/tasks/task-1/edit')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('EditTaskPage', () => {
  it('loads and populates the form with the existing task values', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, EXISTING_TASK)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    expect(screen.getByLabelText(/description/i)).toHaveValue('Make it spotless')
    expect(screen.getByLabelText(/reward points/i)).toHaveValue(20)
    expect(screen.getByLabelText(/^active$/i)).toBeChecked()
    // Assignment/claiming has its own dedicated flow and is never editable here.
    expect(screen.queryByLabelText(/assign/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/^status$/i)).not.toBeInTheDocument()
  })

  it('shows a load error with retry', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, EXISTING_TASK)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    expect(callCount).toBe(2)
  })

  it('shows a not-found state', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) {
          return jsonResponse(404, { error: { code: 'TASK_NOT_FOUND', message: 'Task not found' } })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/task not found/i)).toBeInTheDocument()
    })
  })

  it('saving calls PATCH with only the fields that changed, and returns to Details', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, EXISTING_TASK)
      }
      if (url.endsWith('/api/tasks/task-1') && init?.method === 'PATCH') {
        expect(JSON.parse(init.body as string)).toEqual({
          title: 'Tidy the whole house',
        })
        return jsonResponse(200, { ...EXISTING_TASK, title: 'Tidy the whole house' })
      }
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    fireEvent.change(screen.getByLabelText(/title/i), {
      target: { value: 'Tidy the whole house' },
    })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks/task-1')
    })
  })

  it('saving with reward points and active changed includes both in the PATCH', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, EXISTING_TASK)
      }
      if (url.endsWith('/api/tasks/task-1') && init?.method === 'PATCH') {
        expect(JSON.parse(init.body as string)).toEqual({
          reward_points: 35,
          is_active: false,
        })
        return jsonResponse(200, { ...EXISTING_TASK, reward_points: 35, is_active: false })
      }
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    fireEvent.change(screen.getByLabelText(/reward points/i), { target: { value: '35' } })
    fireEvent.click(screen.getByLabelText(/^active$/i))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks/task-1')
    })
  })

  it('saving with nothing changed sends an empty PATCH body', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, EXISTING_TASK)
      }
      if (url.endsWith('/api/tasks/task-1') && init?.method === 'PATCH') {
        expect(JSON.parse(init.body as string)).toEqual({})
        return jsonResponse(200, EXISTING_TASK)
      }
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks/task-1')
    })
  })

  it('displays an API error on save failure and stays on the form', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/tasks/task-1') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse(200, EXISTING_TASK)
        }
        if (url.endsWith('/api/tasks/task-1') && init?.method === 'PATCH') {
          return jsonResponse(403, {
            error: { code: 'FORBIDDEN', message: 'Cannot edit this task' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/title/i)).toHaveValue('Tidy the room')
    })
    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Changed' } })
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByText('Cannot edit this task')).toBeInTheDocument()
    })
    expect(window.location.pathname).toBe('/tasks/task-1/edit')
  })

  it('Cancel returns to Details without saving', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/tasks/task-1')) return jsonResponse(200, EXISTING_TASK)
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('link', { name: /cancel/i })).toHaveAttribute(
        'href',
        '/tasks/task-1',
      )
    })
  })
})
