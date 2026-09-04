import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PinDots from './PinDots'

describe('PinDots', () => {
  it('renders progress as text for assistive tech, not just visual dots', () => {
    render(<PinDots length={2} />)

    expect(screen.getByRole('status', { name: '2 of 4 digits entered' })).toBeInTheDocument()
  })

  it('renders 4 dots by default, with the entered count marked filled', () => {
    const { container } = render(<PinDots length={3} />)

    const dots = container.querySelectorAll('.pin-dot')
    expect(dots).toHaveLength(4)
    const filled = container.querySelectorAll('.pin-dot-filled')
    expect(filled).toHaveLength(3)
  })
})
