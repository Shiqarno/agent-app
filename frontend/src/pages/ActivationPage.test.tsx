import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ActivationPage from './ActivationPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const USER = { id: 'user-1', name: 'Alice', role: 'adult', avatar_id: 'avatar_01' }

afterEach(() => {
  vi.unstubAllGlobals()
})

function fillPin(pin: string, confirm = pin) {
  fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
  fireEvent.change(screen.getByLabelText(/^pin$/i), { target: { value: pin } })
  fireEvent.change(screen.getByLabelText(/confirm pin/i), { target: { value: confirm } })
}

describe('ActivationPage', () => {
  it('PIN is required: an empty PIN blocks submission without calling the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<ActivationPage token="tok" onActivated={() => {}} />)
    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toBeInTheDocument()
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('mismatched PIN confirmation blocks submission without calling the API', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<ActivationPage token="tok" onActivated={() => {}} />)
    fillPin('1234', '4321')
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/do not match/i)
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('password fields are optional: submitting with them empty still succeeds, with no password sent', async () => {
    const onActivated = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/auth/activate')) {
          const body = JSON.parse(init?.body as string)
          expect(body).toEqual({ token: 'tok', email: 'alice@example.com', pin: '1234' })
          expect(body.password).toBeUndefined()
          return jsonResponse(200, USER)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<ActivationPage token="tok" onActivated={onActivated} />)
    fillPin('1234')
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(onActivated).toHaveBeenCalledWith(USER)
    })
  })

  it('providing both PIN and password works and sends both', async () => {
    const onActivated = vi.fn()
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/auth/activate')) {
          expect(JSON.parse(init?.body as string)).toEqual({
            token: 'tok',
            email: 'alice@example.com',
            pin: '1234',
            password: 'a-password-1',
          })
          return jsonResponse(200, USER)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    render(<ActivationPage token="tok" onActivated={onActivated} />)
    fillPin('1234')
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: 'a-password-1' } })
    fireEvent.change(screen.getByLabelText(/confirm password/i), {
      target: { value: 'a-password-1' },
    })
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(onActivated).toHaveBeenCalledWith(USER)
    })
  })

  it('mismatched password confirmation blocks submission when a password is entered', async () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<ActivationPage token="tok" onActivated={() => {}} />)
    fillPin('1234')
    fireEvent.change(screen.getByLabelText(/^password/i), { target: { value: 'a-password-1' } })
    fireEvent.change(screen.getByLabelText(/confirm password/i), { target: { value: 'different' } })
    fireEvent.click(screen.getByRole('button', { name: /activate/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent(/passwords do not match/i)
    })
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
