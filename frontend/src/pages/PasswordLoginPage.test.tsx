import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { RouterProvider } from '../router'
import PasswordLoginPage from './PasswordLoginPage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

function renderPage(onLogin = vi.fn()) {
  return render(
    <RouterProvider>
      <PasswordLoginPage onLogin={onLogin} />
    </RouterProvider>,
  )
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('PasswordLoginPage', () => {
  it('renders the email/password form', () => {
    renderPage()

    expect(screen.getByRole('heading', { name: /sign in/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/email/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/password/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('has a link back to the default profile/PIN login', () => {
    renderPage()

    expect(screen.getByRole('link', { name: /profile selection/i })).toHaveAttribute(
      'href',
      '/login',
    )
  })

  it('successful login calls onLogin with the returned user', async () => {
    const onLogin = vi.fn()
    const user = { id: 'user-1', name: 'Alice', role: 'adult', avatar_id: 'avatar_01' }
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string, init?: RequestInit) => {
        if (url.endsWith('/api/auth/login')) {
          expect(JSON.parse(init?.body as string)).toEqual({
            email: 'alice@example.com',
            password: 'a-password-1',
          })
          return jsonResponse(200, user)
        }
        throw new Error(`Unexpected request: ${url}`)
      }),
    )

    renderPage(onLogin)

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'a-password-1' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(onLogin).toHaveBeenCalledWith(user)
    })
  })

  it('shows an error on failed login', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse(401, { error: { code: 'INVALID_CREDENTIALS', message: 'Invalid credentials' } }),
      ),
    )

    renderPage()

    fireEvent.change(screen.getByLabelText(/email/i), { target: { value: 'alice@example.com' } })
    fireEvent.change(screen.getByLabelText(/password/i), { target: { value: 'wrong' } })
    fireEvent.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Invalid credentials')).toBeInTheDocument()
    })
  })
})
