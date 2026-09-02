import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ProjectsPage from './ProjectsPage'
import type { Project } from './api/projects'

function project(overrides: Partial<Project> = {}): Project {
  return {
    id: '11111111-1111-1111-1111-111111111111',
    name: 'My first project',
    description: 'A test project',
    created_at: '2026-09-01T12:00:00Z',
    updated_at: '2026-09-01T12:00:00Z',
    ...overrides,
  }
}

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProjectsPage', () => {
  it('shows a loading state before the project list resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    render(<ProjectsPage />)

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders the project list', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [project()])),
    )

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText('My first project')).toBeInTheDocument()
    })
    expect(screen.getByText('A test project')).toBeInTheDocument()
  })

  it('shows an empty state when there are no projects', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, [])),
    )

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText(/no projects/i)).toBeInTheDocument()
    })
  })

  it('creates a project and adds it to the list without a page reload', async () => {
    const created = project({
      id: '22222222-2222-2222-2222-222222222222',
      name: 'New project',
      description: null,
    })
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (!init?.method) {
        return jsonResponse(200, [])
      }
      if (init.method === 'POST') {
        return jsonResponse(201, created)
      }
      throw new Error(`Unexpected request: ${init.method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText(/no projects/i)).toBeInTheDocument()
    })

    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'New project' } })
    fireEvent.click(screen.getByRole('button', { name: /new project/i }))

    await waitFor(() => {
      expect(screen.getByText('New project')).toBeInTheDocument()
    })
  })

  it('edits a project and shows the updated values', async () => {
    const existing = project()
    const updated = { ...existing, name: 'Renamed project', description: 'Updated description' }
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (!init?.method) {
        return jsonResponse(200, [existing])
      }
      if (init.method === 'PUT') {
        return jsonResponse(200, updated)
      }
      throw new Error(`Unexpected request: ${init.method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText('My first project')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Renamed project' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Renamed project')).toBeInTheDocument()
    })
    expect(screen.getByText('Updated description')).toBeInTheDocument()
  })

  it('deletes a project and removes it from the list', async () => {
    const existing = project()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (!init?.method) {
        return jsonResponse(200, [existing])
      }
      if (init.method === 'DELETE') {
        return jsonResponse(204, undefined)
      }
      throw new Error(`Unexpected request: ${init.method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText('My first project')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /delete/i }))

    await waitFor(() => {
      expect(screen.queryByText('My first project')).not.toBeInTheDocument()
    })
  })

  it('shows the backend error message when the project list fails to load with a malformed body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(500, {})),
    )

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText(/request failed with status 500/i)).toBeInTheDocument()
    })
  })

  it('displays the structured backend error message on a failed update', async () => {
    const existing = project()
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      if (!init?.method) {
        return jsonResponse(200, [existing])
      }
      if (init.method === 'PUT') {
        return jsonResponse(404, {
          error: { code: 'PROJECT_NOT_FOUND', message: 'Project not found' },
        })
      }
      throw new Error(`Unexpected request: ${init.method}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText('My first project')).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /edit/i }))
    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'Renamed project' } })
    fireEvent.click(screen.getByRole('button', { name: /save/i }))

    await waitFor(() => {
      expect(screen.getByText('Project not found')).toBeInTheDocument()
    })
    expect(screen.queryByText(/failed to update project/i)).not.toBeInTheDocument()
  })

  it('shows a useful fallback on a genuine network failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject('network down')),
    )

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText(/unable to load projects/i)).toBeInTheDocument()
    })
  })

  it('prevents submitting an empty name', async () => {
    const fetchMock = vi.fn(() => jsonResponse(200, []))
    vi.stubGlobal('fetch', fetchMock)

    render(<ProjectsPage />)

    await waitFor(() => {
      expect(screen.getByText(/no projects/i)).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /new project/i }))

    expect(await screen.findByRole('alert')).toHaveTextContent(/name is required/i)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})
