import '@testing-library/jest-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import PageHeader from './PageHeader'

describe('PageHeader', () => {
  it('renders the title as a heading', () => {
    render(<PageHeader title="Tasks" />)

    expect(screen.getByRole('heading', { name: 'Tasks' })).toBeInTheDocument()
  })

  it('renders the action when given', () => {
    render(<PageHeader title="Tasks" action={<a href="/tasks/new">+ Create task</a>} />)

    expect(screen.getByRole('link', { name: '+ Create task' })).toBeInTheDocument()
  })

  it('renders children between the title and the action', () => {
    render(
      <PageHeader title="Rewards" action={<a href="/rewards/new">+ Create reward</a>}>
        <p>Your balance: 40 points</p>
      </PageHeader>,
    )

    expect(screen.getByText('Your balance: 40 points')).toBeInTheDocument()
  })
})
