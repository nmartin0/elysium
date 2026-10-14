import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'

import EmptyState from './EmptyState'

describe('EmptyState (DEV_UI 9.7, E2)', () => {
  it('says what is empty, why, and offers the way out', () => {
    render(
      <EmptyState
        icon="filter-remove"
        title="No matches"
        reason="No Customer matches the filters you have applied."
        action={<button type="button">Clear filters</button>}
      />,
    )

    expect(screen.getByText('No matches')).toBeInTheDocument()
    expect(screen.getByText('No Customer matches the filters you have applied.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear filters' })).toBeInTheDocument()
  })
})
