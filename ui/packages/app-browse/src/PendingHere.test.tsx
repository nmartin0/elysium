import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

import { PendingInSet, PendingOnObject } from './PendingHere'

const wrap = (node: React.ReactNode) => render(<MemoryRouter>{node}</MemoryRouter>)

const WRITE = { write_id: 'w1', action_type_name: 'Recategorize', awaiting_your_review: true, proposed_by_you: false }

describe('a change waiting, shown where it would land (DEV_UI 15.3)', () => {
  it('on an object: which action, whose decision, and the way to it', () => {
    wrap(<PendingOnObject pending={[WRITE]} />)

    expect(screen.getByText(/A change to this object is waiting for approval: Recategorize/)).toBeInTheDocument()
    expect(screen.getByText(/the decision is yours/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open the Inbox' }).getAttribute('href')).toBe('/inbox?tab=approvals')
  })

  it('a change someone else decides does not claim to be yours', () => {
    wrap(<PendingOnObject pending={[{ ...WRITE, awaiting_your_review: false, proposed_by_you: true }]} />)

    expect(screen.queryByText(/yours/)).toBeNull()
  })

  it('on a set: how many of those shown', () => {
    wrap(<PendingInSet count={3} shown={40} />)

    expect(screen.getByRole('link', { name: '3 of these 40 have changes waiting' })).toBeInTheDocument()
  })

  it('says nothing at all when nothing is waiting', () => {
    const { container } = wrap(
      <>
        <PendingOnObject pending={[]} />
        <PendingInSet count={0} shown={40} />
      </>,
    )

    expect(container.textContent).toBe('')
  })
})
