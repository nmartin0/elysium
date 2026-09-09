import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import ViewSelector, { type ViewOption } from './ViewSelector'

const VIEWS: readonly ViewOption[] = [
  { id: 'users', label: 'Users', icon: 'people' },
  { id: 'silos', label: 'Silos', icon: 'database' },
]

describe('ViewSelector', () => {
  it('reports the choice without deciding what it means', () => {
    // It renders a list and reports a choice. A component that also
    // decided what to SHOW would have to know every sub-app, which is
    // the coupling the sub-app split exists to avoid.
    const onSelect = vi.fn()
    render(<ViewSelector views={VIEWS} selected="users" onSelect={onSelect} />)

    fireEvent.click(screen.getByRole('button', { name: 'Silos' }))

    expect(onSelect).toHaveBeenCalledWith('silos')
  })

  it('announces which view is current', () => {
    /**
     * aria-pressed, because Blueprint's `active` is a VISUAL state that
     * announces nothing. A selector whose current choice is invisible
     * to a screen reader is a selector you cannot use without sight --
     * and this is the primary navigation of every sub-app.
     */
    render(<ViewSelector views={VIEWS} selected="users" onSelect={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Users' }))
      .toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: 'Silos' }))
      .toHaveAttribute('aria-pressed', 'false')
  })

  it('names the group', () => {
    render(<ViewSelector views={VIEWS} selected="users" onSelect={vi.fn()} label="Section" />)

    expect(screen.getByText('Section')).toBeInTheDocument()
  })
})
