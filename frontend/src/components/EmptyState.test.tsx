import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import EmptyState from './EmptyState'

describe('EmptyState', () => {
  it('shows the message', () => {
    render(<EmptyState message="No tasks yet." />)

    expect(screen.getByText('No tasks yet.')).toBeInTheDocument()
  })

  it('renders an action when given', () => {
    render(<EmptyState message="No tasks yet." action={<a href="/tasks/new">Create task</a>} />)

    expect(screen.getByRole('link', { name: 'Create task' })).toBeInTheDocument()
  })

  it('renders no action when none is given', () => {
    render(<EmptyState message="No tasks yet." />)

    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
})
