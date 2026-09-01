import '@testing-library/jest-dom'
import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('App', () => {
  it('shows a loading state before the health check resolves', () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {})),
    )

    render(<App />)

    expect(screen.getByText(/loading/i)).toBeInTheDocument()
  })

  it('renders application and database status on a successful response', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: true,
          json: () => Promise.resolve({ status: 'ok', database: 'ok' }),
        }),
      ),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/application:\s*ok/i)).toBeInTheDocument()
    })
    expect(screen.getByText(/database:\s*ok/i)).toBeInTheDocument()
  })

  it('shows an error state when the backend request fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve({
          ok: false,
          json: () => Promise.resolve({ status: 'error', database: 'unavailable' }),
        }),
      ),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/unable to reach the backend/i)).toBeInTheDocument()
    })
  })

  it('shows an error state when the request throws (network failure)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => Promise.reject(new Error('network error'))),
    )

    render(<App />)

    await waitFor(() => {
      expect(screen.getByText(/unable to reach the backend/i)).toBeInTheDocument()
    })
  })
})
