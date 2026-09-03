import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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

function stubSuccessfulCreation() {
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
}

async function submitTaskForm() {
  await waitFor(() => {
    expect(screen.getByRole('option', { name: /kiddo/i })).toBeInTheDocument()
  })

  fireEvent.change(screen.getByLabelText(/title/i), { target: { value: 'Tidy up' } })
  fireEvent.change(screen.getByLabelText(/reward points/i), { target: { value: '5' } })
  fireEvent.click(screen.getByRole('button', { name: /create task/i }))
}

beforeEach(() => {
  window.history.pushState({}, '', '/tasks/new')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('NewTaskPage', () => {
  // /tasks/new is a single shared creation flow reached from two entry
  // points (Dashboard's "Create task" Quick Action and the Tasks page's own
  // "+ Create task"), each tagging the link with ?from=... . Both must be
  // preserved: entering from /tasks returns to /tasks, entering from the
  // Dashboard returns to /dashboard.

  it('entering from the Tasks page (?from=tasks) returns to /tasks after creation', async () => {
    window.history.pushState({}, '', '/tasks/new?from=tasks')
    stubSuccessfulCreation()

    renderPage()
    await submitTaskForm()

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks')
    })
  })

  it('entering from the Dashboard Quick Action (?from=dashboard) returns to /dashboard after creation', async () => {
    window.history.pushState({}, '', '/tasks/new?from=dashboard')
    stubSuccessfulCreation()

    renderPage()
    await submitTaskForm()

    await waitFor(() => {
      expect(window.location.pathname).toBe('/dashboard')
    })
  })

  it('with no ?from param (direct navigation) defaults to returning to /tasks', async () => {
    window.history.pushState({}, '', '/tasks/new')
    stubSuccessfulCreation()

    renderPage()
    await submitTaskForm()

    await waitFor(() => {
      expect(window.location.pathname).toBe('/tasks')
    })
  })
})
