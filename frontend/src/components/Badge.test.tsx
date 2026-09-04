import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import Badge from './Badge'

describe('Badge', () => {
  it('renders its children text', () => {
    render(<Badge tone="success">Completed</Badge>)

    expect(screen.getByText('Completed')).toBeInTheDocument()
  })

  it('defaults to the neutral tone', () => {
    render(<Badge>Assigned</Badge>)

    expect(screen.getByText('Assigned')).toHaveClass('badge-neutral')
  })

  it('applies the requested tone class', () => {
    render(<Badge tone="error">Cancelled</Badge>)

    expect(screen.getByText('Cancelled')).toHaveClass('badge-error')
  })
})
