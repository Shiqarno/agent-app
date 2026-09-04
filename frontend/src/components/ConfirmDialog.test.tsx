import '@testing-library/jest-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import ConfirmDialog from './ConfirmDialog'

describe('ConfirmDialog', () => {
  it('renders nothing when not open', () => {
    render(
      <ConfirmDialog
        open={false}
        title="Cancel task"
        message="Are you sure?"
        confirmLabel="Cancel task"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )

    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument()
  })

  it('renders with the correct role and content when open', () => {
    render(
      <ConfirmDialog
        open
        title="Cancel task"
        message="Are you sure?"
        confirmLabel="Cancel task"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    )

    const dialog = screen.getByRole('alertdialog')
    expect(dialog).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByText('Are you sure?')).toBeInTheDocument()
  })

  it('calls onConfirm and onCancel', () => {
    const onConfirm = vi.fn()
    const onCancel = vi.fn()
    render(
      <ConfirmDialog
        open
        title="Cancel task"
        message="Are you sure?"
        confirmLabel="Cancel task"
        onConfirm={onConfirm}
        onCancel={onCancel}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Cancel task' }))
    expect(onConfirm).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
