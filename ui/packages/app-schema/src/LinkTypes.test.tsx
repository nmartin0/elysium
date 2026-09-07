import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

import LinkTypes, { groupLinkTypes } from './LinkTypes'

// Both sides of one relationship, as the API actually returns them:
// two fields on two object types, joined only by link_type.
const SCHEMA = {
  Customer: {
    display_name: 'Customer',
    fields: {
      transactions: {
        type: 'link', display_name: 'Transactions', target: 'Transaction',
        cardinality: 'many', link_type: 'CustomerTransactions',
      },
    },
  },
  Transaction: {
    display_name: 'Transaction',
    fields: {
      customer_id: {
        type: 'link', display_name: 'Customer', target: 'Customer',
        cardinality: 'one', link_type: 'CustomerTransactions',
      },
      amount: { type: 'data', display_name: 'Amount' },
    },
  },
}

describe('groupLinkTypes', () => {
  it('joins both sides of a relationship under one link type', () => {
    // The API returns link FIELDS, not link types -- one relationship
    // arrives as two fields on two object types. Presenting them
    // ungrouped would show one relationship as two unrelated columns.
    const grouped = groupLinkTypes(SCHEMA)

    expect(grouped.size).toBe(1)
    expect(grouped.get('CustomerTransactions')).toHaveLength(2)
  })

  it('ignores data fields', () => {
    const sides = groupLinkTypes(SCHEMA).get('CustomerTransactions')

    expect(sides?.map((side) => side.apiName)).not.toContain('amount')
  })

  it('keeps a relationship whose other end the caller cannot read', () => {
    // Uniform denial working, not data loss: a caller granted one end
    // and not the other sees one side. Hiding the whole relationship
    // would withhold something they CAN see.
    const grouped = groupLinkTypes({ Customer: SCHEMA.Customer })

    expect(grouped.get('CustomerTransactions')).toHaveLength(1)
  })

  it('returns nothing for a schema with no links at all', () => {
    expect(groupLinkTypes({ Transaction: { fields: { amount: { type: 'data' } } } }).size).toBe(0)
  })
})

describe('LinkTypes', () => {
  it('renders each side with its cardinality and target', () => {
    render(<LinkTypes schema={SCHEMA} filter="" onOpenObjectType={() => {}} />)

    expect(screen.getByText('CustomerTransactions')).toBeInTheDocument()
    expect(screen.getByText(/many/)).toBeInTheDocument()
    expect(screen.getByText(/one/)).toBeInTheDocument()
  })

  it('says when only one side is visible', () => {
    render(<LinkTypes schema={{ Customer: SCHEMA.Customer }} filter="" onOpenObjectType={() => {}} />)

    expect(screen.getByText(/one side visible to you/)).toBeInTheDocument()
  })

  it('says so plainly when no link type is visible', () => {
    render(<LinkTypes schema={{}} filter="" onOpenObjectType={() => {}} />)

    expect(screen.getByText(/No link types are visible/)).toBeInTheDocument()
  })
})

describe('LinkTypes -- filtering and navigation', () => {
  it('matches on the link type name', () => {
    render(
      <LinkTypes schema={SCHEMA} filter="CustomerTrans" onOpenObjectType={() => {}} />,
    )

    expect(screen.getByText('CustomerTransactions')).toBeInTheDocument()
  })

  it('matches on either end of the relationship', () => {
    // Someone looking for "what links to Transaction" should not have
    // to know the relationship's name to find it.
    render(<LinkTypes schema={SCHEMA} filter="Transaction" onOpenObjectType={() => {}} />)

    expect(screen.getByText('CustomerTransactions')).toBeInTheDocument()
  })

  it('says so when nothing matches', () => {
    render(<LinkTypes schema={SCHEMA} filter="zzz" onOpenObjectType={() => {}} />)

    expect(screen.getByText(/No link type matches/)).toBeInTheDocument()
  })

  it('opens an object type when one end is clicked', () => {
    const onOpenObjectType = vi.fn()
    render(<LinkTypes schema={SCHEMA} filter="" onOpenObjectType={onOpenObjectType} />)

    fireEvent.click(screen.getByRole('button', { name: 'Customer' }))

    expect(onOpenObjectType).toHaveBeenCalledWith('Customer')
  })
})
