import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import NewUserPage from './NewUserPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const CREATED_USER = {
  id: '33333333-3333-3333-3333-333333333333',
  name: 'New Kid',
  role: 'child',
  created_at: '2026-09-03T10:00:00Z',
  updated_at: '2026-09-03T10:00:00Z',
  activation_token: 'raw-activation-token-abc',
}

function renderPage() {
  return render(
    <RouterProvider>
      <NewUserPage />
    </RouterProvider>,
  )
}

beforeEach(() => {
  window.history.pushState({}, '', '/users/new')
})

afterEach(() => {
  vi.unstubAllGlobals()
  window.history.pushState({}, '', '/')
})

describe('NewUserPage', () => {
  it('lets an Adult pick Adult or Child as the role', () => {
    renderPage()

    const roleSelect = screen.getByLabelText(/role/i) as HTMLSelectElement
    const optionValues = Array.from(roleSelect.options).map((option) => option.value)
    expect(optionValues).toEqual(['adult', 'child'])
  })

  it('creates the user and presents an activation link built from the returned token', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/users')) {
        expect(init?.method).toBe('POST')
        expect(JSON.parse(init?.body as string)).toEqual({ name: 'New Kid', role: 'child' })
        return jsonResponse(201, CREATED_USER)
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'New Kid' } })
    fireEvent.click(screen.getByRole('button', { name: /add user/i }))

    await waitFor(() => {
      expect(screen.getByRole('heading', { name: /user created/i })).toBeInTheDocument()
    })

    const expectedUrl = `${window.location.origin}/activate?activation_token=raw-activation-token-abc`
    expect(screen.getByText(expectedUrl)).toBeInTheDocument();
  })

  it('the activation link never appears before creation and the raw token is not sent anywhere else', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(201, CREATED_USER)),
    )

    renderPage()

    expect(screen.queryByText(/activation_token=/i)).not.toBeInTheDocument()
  })

  it('provides a copy action for the activation link', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(201, CREATED_USER)),
    )

    renderPage()

    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'New Kid' } })
    fireEvent.click(screen.getByRole('button', { name: /add user/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /copy link/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /copy link/i }))

    await waitFor(() => {
      expect(writeText).toHaveBeenCalledWith(
        `${window.location.origin}/activate?activation_token=raw-activation-token-abc`,
      )
    })
  })

  it('returns to the Dashboard after finishing the activation-link presentation', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(201, CREATED_USER)),
    )

    renderPage()

    fireEvent.change(screen.getByLabelText(/name/i), { target: { value: 'New Kid' } })
    fireEvent.click(screen.getByRole('button', { name: /add user/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /back to dashboard/i })).toBeInTheDocument()
    })

    fireEvent.click(screen.getByRole('button', { name: /back to dashboard/i }))

    expect(window.location.pathname).toBe('/dashboard')
  })

  it('requires a name before submitting', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    renderPage()

    fireEvent.click(screen.getByRole('button', { name: /add user/i }))

    expect(screen.getByRole('alert')).toHaveTextContent(/name is required/i)
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
