import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import NewTaskPage from './NewTaskPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const USERS = [{ id: 'child-1', name: 'Kiddo', role: 'child' }]

function renderPage() {
  return render(
    <RouterProvider>
      <NewTaskPage />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('NewTaskPage', () => {
  it('returns to /tasks after a successful creation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/users')) return jsonResponse(200, USERS)
        if (url.endsWith('/api/tasks') && init?.method === 'POST') {
          return jsonResponse(201, {
            id: 'task-1',
            title: 'Tidy up',
            description: null,
            assigned_to: 'child-1',
            created_by: 'adult-1',
            reward_points: 5,
            status: 'ASSIGNED',
            created_at: '2026-09-03T10:00:00Z',
            updated_at: '2026-09-03T10:00:00Z',
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('option', { name: /kiddo/i })).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Tidy up' } })
    fireEvent.change(screen.getByLabelText(/reward points/i), { target: { value: '5' } })
    fireEvent.click(screen.getByRole('button', { name: /create task/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks')
    })
  })
})
