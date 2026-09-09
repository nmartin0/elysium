import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

import GraphPreview from './GraphPreview'
import type { VisibleSchema } from '@elysium/shell-api/types'

const SCHEMA: VisibleSchema = {
  Customer: {
    display_name: 'Customer',
    description: 'A person who banks with us.',
    fields: {
      name: { type: 'data', data_type: 'string' },
      secret: { type: 'data', data_type: 'string', visibility: 'hidden' },
      transactions: { type: 'link', target: 'Transaction', link_type: 'CT' },
    },
  },
}

const ACTIONS = {
  UpdateCustomerName: {
    display_name: 'Update name',
    description: 'Corrects a misspelling.',
    affected_object_types: ['Customer'],
  },
}

const props = { schema: SCHEMA, actionTypes: ACTIONS, onOpenFull: vi.fn() }

describe('GraphPreview -- an object type', () => {
  it('shows what the node IS without leaving the graph', () => {
    /**
     * The whole point. Clicking used to navigate to Object types, and
     * returning re-laid the graph out -- so exploring cost you your
     * place every time.
     */
    render(<GraphPreview {...props} selection={{ kind: 'object', name: 'Customer' }} />)

    expect(screen.getByText('A person who banks with us.')).toBeInTheDocument()
    expect(screen.getByText(/Name/)).toBeInTheDocument()
  })

  it('separates links from data fields', () => {
    // Links are the graph's own edges; seeing them beside the picture
    // is what makes the picture legible.
    render(<GraphPreview {...props} selection={{ kind: 'object', name: 'Customer' }} />)

    expect(screen.getByText('Links')).toBeInTheDocument()
    expect(screen.getByText('Transaction')).toBeInTheDocument()
  })

  it('marks a field the author hid', () => {
    // A hidden field shown as equal to a prominent one overstates it.
    // The fixture ontology declares no visibility, so this path is
    // exercised here rather than by the dev deployment.
    render(<GraphPreview {...props} selection={{ kind: 'object', name: 'Customer' }} />)

    expect(screen.getByText('hidden')).toBeInTheDocument()
  })

  it('offers a way out without taking it for you', () => {
    const onOpenFull = vi.fn()
    render(
      <GraphPreview {...props} onOpenFull={onOpenFull}
        selection={{ kind: 'object', name: 'Customer' }} />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Open in Object types/ }))

    expect(onOpenFull).toHaveBeenCalledWith('Customer', 'object')
  })
})

describe('GraphPreview -- an action type', () => {
  it('describes the action and what it touches', () => {
    render(
      <GraphPreview {...props} selection={{ kind: 'action', name: 'UpdateCustomerName' }} />,
    )

    expect(screen.getByText('Update name')).toBeInTheDocument()
    expect(screen.getByText(/Customer/)).toBeInTheDocument()
  })

  it('opens Action types, not Object types', () => {
    const onOpenFull = vi.fn()
    render(
      <GraphPreview {...props} onOpenFull={onOpenFull}
        selection={{ kind: 'action', name: 'UpdateCustomerName' }} />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Open in Action types/ }))

    expect(onOpenFull).toHaveBeenCalledWith('UpdateCustomerName', 'action')
  })
})

describe('GraphPreview -- a link type', () => {
  it('names what the edge joins, which the edge could not', () => {
    /**
     * The edge carries a cardinality; which end is which needs words.
     * Foundry's own version does this too -- "click on a link symbol
     * to show the type of links between the object types".
     */
    render(
      <GraphPreview {...props} selection={{
        kind: 'link', name: 'CustomerTransactions',
        source: 'Customer', target: 'Transaction', label: '1:M',
      }} />,
    )

    expect(screen.getByText('CustomerTransactions')).toBeInTheDocument()
    expect(screen.getByText('1:M')).toBeInTheDocument()
  })
})
