import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import Discover from './Discover'
import { recordVisit, toggleFavourite } from './discoverStorage'

const SCHEMA = {
  Customer: { display_name: 'Customer', status: 'active', fields: {} },
  Transaction: { display_name: 'Transaction', status: 'active', fields: {} },
  LegacyThing: { display_name: 'Legacy Thing', status: 'deprecated', fields: {} },
}

const props = {
  schema: SCHEMA,
  username: 'alice',
  version: 0,
  onOpen: vi.fn(),
  onFavouriteChange: vi.fn(),
}

beforeEach(() => {
  window.localStorage.clear()
  props.onOpen.mockReset()
  props.onFavouriteChange.mockReset()
})

describe('Discover', () => {
  it('separates deprecated types from active ones', () => {
    // The ontology author declared this; no storage needed. Mixing a
    // deprecated type in with current ones invites someone to build
    // against something on its way out.
    render(<Discover {...props} />)

    expect(screen.getByText('Deprecated')).toBeInTheDocument()
    expect(screen.getByText('Legacy Thing')).toBeInTheDocument()
  })

  it('shows recently viewed types most recent first', () => {
    recordVisit('alice', 'Customer')
    recordVisit('alice', 'Transaction')

    render(<Discover {...props} />)

    expect(screen.getByText('Recently viewed')).toBeInTheDocument()
  })

  it('opens a type when its name is clicked', () => {
    render(<Discover {...props} />)

    // getAllByText because the same type appears under both
    // "Recently viewed" and "All active"; either opens it.
    const [firstCustomerButton] = screen.getAllByText('Customer')
    expect(firstCustomerButton).toBeDefined()
    fireEvent.click(firstCustomerButton as HTMLElement)

    expect(props.onOpen).toHaveBeenCalledWith('Customer')
  })

  it('tells the parent when a favourite is toggled', () => {
    // Storage is not reactive, so the parent has to be told or the
    // star does not change until something else re-renders.
    render(<Discover {...props} />)

    const [firstStar] = screen.getAllByLabelText('Favourite Customer')
    expect(firstStar).toBeDefined()
    fireEvent.click(firstStar as HTMLElement)

    expect(props.onFavouriteChange).toHaveBeenCalled()
  })

  it('hides a favourited type the caller can no longer see', () => {
    // THE permission-change case, at the component level. The name is
    // still in storage; the schema no longer lists it, so it does not
    // appear -- no migration, no stale entry offering a type that
    // cannot be opened.
    toggleFavourite('alice', 'Customer')

    render(<Discover {...props} schema={{ Transaction: SCHEMA.Transaction }} />)

    expect(screen.queryByText('Customer')).not.toBeInTheDocument()
  })

  it('says so plainly when the caller can see nothing', () => {
    render(<Discover {...props} schema={{}} />)

    expect(screen.getByText(/do not have read access/)).toBeInTheDocument()
  })

  it('prompts rather than showing an empty area when nothing is stored', () => {
    render(<Discover {...props} />)

    expect(screen.getByText(/Star an object type/)).toBeInTheDocument()
    expect(screen.getByText(/will appear here/)).toBeInTheDocument()
  })
})
