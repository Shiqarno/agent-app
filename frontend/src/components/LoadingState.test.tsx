import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import LoadingState from './LoadingState'

describe('LoadingState', () => {
  it('shows a default label', () => {
    render(<LoadingState />)

    expect(screen.getByText('Loading...')).toBeInTheDocument()
  })

  it('shows a custom label', () => {
    render(<LoadingState label="Loading tasks..." />)

    expect(screen.getByText('Loading tasks...')).toBeInTheDocument()
  })

  it('exposes a status role', () => {
    render(<LoadingState />)

    expect(screen.getByRole('status')).toBeInTheDocument()
  })
})
