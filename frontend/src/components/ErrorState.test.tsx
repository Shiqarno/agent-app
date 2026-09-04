import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ErrorState from './ErrorState'

describe('ErrorState', () => {
  it('shows the message with an alert role', () => {
    render(<ErrorState message="Could not load tasks." />)

    expect(screen.getByRole('alert')).toHaveTextContent('Could not load tasks.')
  })

  it('shows a Retry button when onRetry is given, and calls it', () => {
    const onRetry = vi.fn()
    render(<ErrorState message="Could not load tasks." onRetry={onRetry} />)

    fireEvent.click(screen.getByRole('button', { name: /retry/i }))

    expect(onRetry).toHaveBeenCalledTimes(1)
  })

  it('shows no Retry button when onRetry is not given', () => {
    render(<ErrorState message="Could not load tasks." />)

    expect(screen.queryByRole('button', { name: /retry/i })).not.toBeInTheDocument()
  })
})
