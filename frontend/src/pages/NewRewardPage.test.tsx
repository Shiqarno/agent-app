import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import NewRewardPage from './NewRewardPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const CREATED_REWARD = {
  id: 'reward-1',
  name: 'Extra screen time',
  description: '30 minutes',
  cost_points: 50,
  created_by: 'adult-1',
  created_at: '2026-09-03T10:00:00Z',
  updated_at: '2026-09-03T10:00:00Z',
}

function renderPage() {
  return render(
    <RouterProvider>
      <NewRewardPage />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('NewRewardPage', () => {
  it('renders the creation form', () => {
    renderPage()

    expect(screen.getByLabelText(/^name$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/description/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/cost/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /create reward/i })).toBeInTheDocument()
  })

  it('requires a name before submitting', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/name is required/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('requires a valid positive whole-number cost', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Reward' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '0' } })
    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/cost must be a positive whole number/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('submits valid data and navigates to /rewards on success', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/rewards') && init?.method === 'POST') {
        expect(JSON.parse(init.body as string)).toEqual({
          name: 'Extra screen time',
          description: '30 minutes',
          cost_points: 50,
        })
        return jsonResponse(201, CREATED_REWARD)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Extra screen time' } })
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: '30 minutes' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '50' } })
    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/rewards')
    })
  })

  it('sends description as null when left blank', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/rewards') && init?.method === 'POST') {
        expect(JSON.parse(init.body as string)).toEqual({
          name: 'Reward',
          description: null,
          cost_points: 10,
        })
        return jsonResponse(201, CREATED_REWARD)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Reward' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/rewards')
    })
  })

  it('disables submit while the request is pending', async () => {
    let resolveCreate: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolveCreate = () =>
              resolve({ ok: true, status: 201, json: () => Promise.resolve(CREATED_REWARD) })
          }),
      ),
    )

    renderPage()

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Reward' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
    })

    resolveCreate()

    await waitFor(() => {
      expect(window.location.pathname).toBe('/rewards')
    })
  })

  it('displays a mutation error and keeps entered values on failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse(422, {
          error: { code: 'VALIDATION_ERROR', message: 'Cost must be positive' },
        }),
      ),
    )

    renderPage()

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Reward' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '10' } })
    fireEvent.click(screen.getByRole('button', { name: /create reward/i }))

    await waitFor(() => {
      expect(screen.getByText('Cost must be positive')).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/^name$/i)).toHaveValue('Reward')
    expect(screen.getByLabelText(/cost/i)).toHaveValue(10)
    expect(window.location.pathname).not.toBe('/rewards')
  })
})
