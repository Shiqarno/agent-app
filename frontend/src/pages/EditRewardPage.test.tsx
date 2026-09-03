import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import EditRewardPage from './EditRewardPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const EXISTING_REWARD = {
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
      <EditRewardPage />
    </RouterProvider>,
  )
}

beforeEach(() => {
  window.history.pushState({}, '', '/rewards/reward-1/edit')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('EditRewardPage', () => {
  it('shows a loading state while the reward loads', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    renderPage()

    expect(screen.getByText(/loading reward/i)).toBeInTheDocument()
  })

  it('loads the reward (via the list endpoint) and populates the form', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [EXISTING_REWARD])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Extra screen time')
    })
    expect(screen.getByLabelText(/description/i)).toHaveValue('30 minutes')
    expect(screen.getByLabelText(/cost/i)).toHaveValue(50)
  })

  it('shows a not-found state with a way back when the reward id does not exist', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) return jsonResponse(200, [])
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByText(/reward not found/i)).toBeInTheDocument()
    })
    expect(screen.getByRole('link', { name: /back to rewards/i })).toHaveAttribute(
      'href',
      '/rewards',
    )
    expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument()
  })

  it('shows a load error with retry (and does not render a form with default data)', async () => {
    let callCount = 0
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (url.endsWith('/api/rewards')) {
          callCount += 1
          if (callCount === 1) return jsonResponse(500, {})
          return jsonResponse(200, [EXISTING_REWARD])
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Extra screen time')
    })
    expect(callCount).toBe(2)
  })

  it('submits the updated values (description as a string, never null) and navigates to /rewards', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/rewards') && (init?.method ?? 'GET') === 'GET') {
        return jsonResponse(200, [EXISTING_REWARD])
      }
      if (url.endsWith('/api/rewards/reward-1') && init?.method === 'PATCH') {
        expect(JSON.parse(init.body as string)).toEqual({
          name: 'Renamed reward',
          description: '',
          cost_points: 75,
        })
        return jsonResponse(200, { ...EXISTING_REWARD, name: 'Renamed reward', cost_points: 75 })
      }
      throw new Error(`Unexpected request: ${url} ${String(init?.method)}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Extra screen time')
    })

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Renamed reward' } })
    fireEvent.change(screen.getByLabelText(/description/i), { target: { value: '' } })
    fireEvent.change(screen.getByLabelText(/cost/i), { target: { value: '75' } })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(window.location.pathname).toBe('/rewards')
    })
  })

  it('disables submit while the update is pending', async () => {
    let resolveUpdate: () => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/rewards') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse(200, [EXISTING_REWARD])
        }
        if (url.endsWith('/api/rewards/reward-1') && init?.method === 'PATCH') {
          return new Promise((resolve) => {
            resolveUpdate = () =>
              resolve({ ok: true, status: 200, json: () => Promise.resolve(EXISTING_REWARD) })
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Extra screen time')
    })

    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
    })

    resolveUpdate()

    await waitFor(() => {
      expect(window.location.pathname).toBe('/rewards')
    })
  })

  it('displays a mutation error and preserves entered values on update failure', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/rewards') && (init?.method ?? 'GET') === 'GET') {
          return jsonResponse(200, [EXISTING_REWARD])
        }
        if (url.endsWith('/api/rewards/reward-1') && init?.method === 'PATCH') {
          return jsonResponse(404, {
            error: { code: 'REWARD_NOT_FOUND', message: 'Reward not found' },
          })
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage()

    await waitFor(() => {
      expect(screen.getByLabelText(/^name$/i)).toHaveValue('Extra screen time')
    })

    fireEvent.change(screen.getByLabelText(/^name$/i), { target: { value: 'Renamed reward' } })
    fireEvent.click(screen.getByRole('button', { name: /save changes/i }))

    await waitFor(() => {
      expect(screen.getByText('Reward not found')).toBeInTheDocument()
    })
    expect(screen.getByLabelText(/^name$/i)).toHaveValue('Renamed reward')
    expect(window.location.pathname).not.toBe('/rewards')
  })
})
