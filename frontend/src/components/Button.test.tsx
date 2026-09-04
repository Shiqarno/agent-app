import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import Button from './Button'

describe('Button', () => {
  it('renders a real button element', () => {
    render(<Button>Save</Button>)

    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })

  it('applies the primary variant class by default', () => {
    render(<Button>Save</Button>)

    expect(screen.getByRole('button')).toHaveClass('btn-primary')
  })

  it('applies the requested variant class', () => {
    render(<Button variant="destructive">Delete</Button>)

    expect(screen.getByRole('button')).toHaveClass('btn-destructive')
  })

  it('calls the click handler', () => {
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Save</Button>)

    fireEvent.click(screen.getByRole('button'))

    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('is disabled and marked busy while loading, and does not fire clicks', () => {
    const onClick = vi.fn()
    render(
      <Button loading onClick={onClick}>
        Saving...
      </Button>,
    )

    const button = screen.getByRole('button')
    expect(button).toBeDisabled()
    expect(button).toHaveAttribute('aria-busy', 'true')

    fireEvent.click(button)
    expect(onClick).not.toHaveBeenCalled()
  })

  it('respects an explicit disabled prop', () => {
    render(<Button disabled>Save</Button>)

    expect(screen.getByRole('button')).toBeDisabled()
  })
})
