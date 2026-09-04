import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import PinSetupRequiredPage from './PinSetupRequiredPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const USER = {
  id: 'user-1',
  name: 'Alice',
  role: 'adult' as const,
  avatar_id: 'avatar_01',
  pin_configured: false,
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PinSetupRequiredPage', () => {
  it('renders the mandatory setup form with no skip control', () => {
    render(<PinSetupRequiredPage user={USER} onComplete={() => {}} onLogout={() => {}} />)

    expect(screen.getByRole('heading', { name: /set up your pin/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/choose a 4-digit pin/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/confirm your pin/i)).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: /skip|later/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /skip|later/i })).not.toBeInTheDocument()
  })

  it('a mismatched confirmation shows a validation error and does not call the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<PinSetupRequiredPage user={USER} onComplete={() => {}} onLogout={() => {}} />)

    fireEvent.change(screen.getByLabelText(/choose a 4-digit pin/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/confirm your pin/i), { target: { value: '4321' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/do not match/i)
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('matching valid PINs call setupPin and then onComplete on success', async () => {
    const onComplete = vi.fn()
    const updated = { ...USER, pin_configured: true }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/auth/pin')) {
          expect(init?.method).toBe('PATCH')
          expect(JSON.parse(init?.body as string)).toEqual({ pin: '1234' })
          return jsonResponse(200, updated)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<PinSetupRequiredPage user={USER} onComplete={onComplete} onLogout={() => {}} />)

    fireEvent.change(screen.getByLabelText(/choose a 4-digit pin/i), { target: { value: '1234' } })
    fireEvent.change(screen.getByLabelText(/confirm your pin/i), { target: { value: '1234' } })
    fireEvent.click(screen.getByRole('button', { name: /continue/i }))

    await waitFor(() => {
      expect(onComplete).toHaveBeenCalledWith(updated)
    })
  })

  it('the logout control calls onLogout', () => {
    const onLogout = vi.fn()
    render(<PinSetupRequiredPage user={USER} onComplete={() => {}} onLogout={onLogout} />)

    fireEvent.click(screen.getByRole('button', { name: /log out/i }))

    expect(onLogout).toHaveBeenCalled()
  })
})
