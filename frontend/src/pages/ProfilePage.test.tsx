import '@testing-library/jest-dom'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import ProfilePage from './ProfilePage'

function jsonResponse(status: number, body: unknown) {
  return Promise.resolve({
    ok: status >= 200 && status < 300,
    status,
    json: () => Promise.resolve(body),
  })
}

const CURRENT_USER = {
  id: 'user-1',
  name: 'Alice',
  role: 'adult' as const,
  avatar_id: 'avatar_01',
}

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('ProfilePage', () => {
  it('renders the current avatar', () => {
    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={() => {}} />)

    expect(screen.getByAltText(/your current avatar/i)).toBeInTheDocument()
  })

  it('selecting a different avatar in the picker does not call the API', () => {
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)

    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={() => {}} />)

    const buttons = screen.getAllByRole('button', { name: /avatar option/i })
    fireEvent.click(buttons[2])

    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('Save is disabled until a different avatar is selected', () => {
    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={() => {}} />)

    expect(screen.getByRole('button', { name: /^save$/i })).toBeDisabled()

    const buttons = screen.getAllByRole('button', { name: /avatar option/i })
    fireEvent.click(buttons[2])

    expect(screen.getByRole('button', { name: /^save$/i })).toBeEnabled()
  })

  it('clicking Save calls PATCH /api/users/me with the selected avatar id', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith('/api/users/me')) {
        expect(init?.method).toBe('PATCH')
        expect(JSON.parse(init?.body as string)).toEqual({ avatar_id: 'avatar_03' })
        return jsonResponse(200, { ...CURRENT_USER, avatar_id: 'avatar_03' })
      }
      throw new Error(`Unexpected request: ${url}`)
    })
    vi.stubGlobal('fetch', fetchMock)

    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /avatar option avatar_03/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(1)
    })
  })

  it('success calls onUpdated with the new user', async () => {
    const updated = { ...CURRENT_USER, avatar_id: 'avatar_03' }
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse(200, updated)),
    )
    const onUpdated = vi.fn()

    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={onUpdated} />)

    fireEvent.click(screen.getByRole('button', { name: /avatar option avatar_03/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(onUpdated).toHaveBeenCalledWith(updated)
    })
  })

  it('Save is disabled while the request is pending, preventing double submit', async () => {
    let resolveRequest: (value: unknown) => void = () => {}
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise((resolve) => {
            resolveRequest = resolve
          }),
      ),
    )

    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={() => {}} />)

    fireEvent.click(screen.getByRole('button', { name: /avatar option avatar_03/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /saving/i })).toBeDisabled()
    })

    resolveRequest(jsonResponse(200, { ...CURRENT_USER, avatar_id: 'avatar_03' }))

    await waitFor(() => {
      expect(screen.getByRole('button', { name: /^save$/i })).toBeEnabled()
    })
  })

  it('failure shows an error, does not call onUpdated, and leaves the previously-saved avatar shown', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse(500, { error: { code: 'SERVER_ERROR', message: 'Could not save avatar' } }),
      ),
    )
    const onUpdated = vi.fn()

    render(<ProfilePage currentUser={CURRENT_USER} onUpdated={onUpdated} />)

    fireEvent.click(screen.getByRole('button', { name: /avatar option avatar_03/i }))
    fireEvent.click(screen.getByRole('button', { name: /^save$/i }))

    await waitFor(() => {
      expect(screen.getByText('Could not save avatar')).toBeInTheDocument()
    })
    expect(onUpdated).not.toHaveBeenCalled()
    // The "current avatar" display (backed by the still-unchanged prop) is
    // untouched -- no optimistic update happened.
    expect(screen.getByAltText(/your current avatar/i)).toHaveAttribute(
      'src',
      expect.stringContaining('avatar-01'),
    )
  })
})
