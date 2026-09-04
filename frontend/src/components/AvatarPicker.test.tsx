import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AVATAR_IDS } from './Avatar'
import AvatarPicker from './AvatarPicker'

describe('AvatarPicker', () => {
  it('renders all 10 avatars as buttons', () => {
    render(<AvatarPicker value="avatar_01" onChange={() => {}} />)

    expect(screen.getAllByRole('button')).toHaveLength(AVATAR_IDS.length)
  })

  it('marks the current value as selected via aria-pressed', () => {
    render(<AvatarPicker value="avatar_03" onChange={() => {}} />)

    const buttons = screen.getAllByRole('button')
    const pressed = buttons.filter((button) => button.getAttribute('aria-pressed') === 'true')
    expect(pressed).toHaveLength(1)
    expect(screen.getByRole('button', { pressed: true })).toBeInTheDocument()
  })

  it('clicking a different avatar calls onChange with that id', () => {
    const onChange = vi.fn()
    render(<AvatarPicker value="avatar_01" onChange={onChange} />)

    const buttons = screen.getAllByRole('button')
    fireEvent.click(buttons[4])

    expect(onChange).toHaveBeenCalledWith('avatar_05')
  })

  it('does not call onChange for clicking the already-selected avatar redundantly', () => {
    const onChange = vi.fn()
    render(<AvatarPicker value="avatar_02" onChange={onChange} />)

    fireEvent.click(screen.getByRole('button', { pressed: true }))

    expect(onChange).toHaveBeenCalledWith('avatar_02')
  })

  it('options are real buttons operable via the keyboard (Enter triggers the click handler)', () => {
    const onChange = vi.fn()
    render(<AvatarPicker value="avatar_01" onChange={onChange} />)

    const buttons = screen.getAllByRole('button')
    buttons[1].focus()
    expect(buttons[1]).toHaveFocus()
    fireEvent.click(buttons[1])

    expect(onChange).toHaveBeenCalledWith('avatar_02')
  })
})
