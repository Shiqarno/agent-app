import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import PinPad from './PinPad'

describe('PinPad', () => {
  it('renders exactly digits 0-9, each once', () => {
    render(<PinPad onDigit={() => {}} />)

    const buttons = screen.getAllByRole('button')
    const labels = buttons.map((button) => button.textContent)
    expect(new Set(labels)).toEqual(new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']))
    expect(buttons).toHaveLength(10)
  })

  it('tapping a digit calls onDigit with that digit', () => {
    const onDigit = vi.fn()
    render(<PinPad onDigit={onDigit} />)

    fireEvent.click(screen.getByRole('button', { name: 'Digit 7' }))

    expect(onDigit).toHaveBeenCalledWith('7')
  })

  it('disables every key when disabled', () => {
    render(<PinPad onDigit={() => {}} disabled />)

    for (const button of screen.getAllByRole('button')) {
      expect(button).toBeDisabled()
    }
  })

  it('remounting still renders all 10 digits exactly once (shuffle never drops or duplicates a digit)', () => {
    for (let attempt = 0; attempt < 20; attempt++) {
      const { unmount } = render(<PinPad key={attempt} onDigit={() => {}} />)
      const labels = screen.getAllByRole('button').map((button) => button.textContent)
      expect(new Set(labels)).toEqual(new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9']))
      unmount()
    }
  })
})
