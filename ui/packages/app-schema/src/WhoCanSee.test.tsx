import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type { TypeAccess } from '@elysium/shell-api/api'
import WhoCanSee from './WhoCanSee'

/** What the route answers, per test. A plain function rather than a
 *  vi.fn: a rejection returned THROUGH a vi.fn surfaced as a test
 *  failure even though the hook handled it, where the same rejection
 *  from a plain function -- as useFetchOnce.test does it -- did not. */
let answer: () => Promise<unknown> = () => new Promise(() => {})
vi.mock('@elysium/shell-api/api', async (original) => ({
  ...(await original<typeof import('@elysium/shell-api/api')>()),
  getSchemaAccess: () => answer(),
}))

/** As the route serves it for the fixture's Customer and Transaction. */
const CUSTOMER: TypeAccess = {
  object_type: 'Customer',
  roles: [
    {
      role: 'editor',
      holders: 3,
      type: 'read',
      actions: ['CreateCustomer', 'UpdateCustomerName'],
      fields: { region: 'read', name: 'read', email: 'read' },
    },
    {
      role: 'cs_no_email',
      holders: 0,
      type: 'read',
      actions: [],
      fields: { region: null, name: 'read', email: 'discover' },
    },
  ],
  no_access: ['admin'],
  compartment: { attribute: 'region', path: [], type: 'Customer', field: 'region' },
}

describe('WhoCanSee (DEV_UI 13.3)', () => {
  it('says which objects, by compartment, in a sentence', () => {
    render(<WhoCanSee objectType="Customer" access={CUSTOMER} />)

    expect(screen.getByText('A person sees a Customer only when their region matches its region.')).toBeInTheDocument()
  })

  it('follows a borrowed compartment to the field that is compared', () => {
    render(
      <WhoCanSee
        objectType="Transaction"
        access={{
          ...CUSTOMER,
          compartment: {
            attribute: 'region',
            path: [{ type: 'Transaction', field: 'customer_id' }],
            type: 'Customer',
            field: 'region',
          },
        }}
      />,
    )

    expect(
      screen.getByText(/matches its Customer's region, followed through Transaction.customer_id → Customer.region/),
    ).toBeInTheDocument()
  })

  it('says a type is unrestricted outright, not as a missing compartment (19 October)', () => {
    render(
      <WhoCanSee
        objectType="Product"
        access={{
          ...CUSTOMER,
          compartment: { attribute: 'region', path: [], type: 'Product', field: null, unrestricted: true },
        }}
      />,
    )

    expect(screen.getByText(/Product is declared unrestricted: .* whatever their region/)).toBeInTheDocument()
    expect(screen.queryByText(/No compartment is declared/)).toBeNull()
  })

  it('says when no compartment is declared rather than nothing', () => {
    render(<WhoCanSee objectType="Note" access={{ ...CUSTOMER, compartment: null }} />)

    expect(screen.getByText(/No compartment is declared/)).toBeInTheDocument()
  })

  it('summarises each role: people, fields read, known, hidden, and actions', () => {
    render(<WhoCanSee objectType="Customer" access={CUSTOMER} />)

    const editor = screen.getByText('editor').closest('tr') as HTMLElement
    expect(editor).toHaveTextContent('3')
    expect(editor).toHaveTextContent('all 3')
    expect(editor).toHaveTextContent('CreateCustomer, UpdateCustomerName')
    const limited = screen.getByText('cs_no_email').closest('tr') as HTMLElement
    expect(limited).toHaveTextContent('reads 1 of 3; knows email exists; cannot see region')
    expect(limited).toHaveTextContent('no action')
    expect(screen.getByText('Cannot know it exists: admin.')).toBeInTheDocument()
  })
})

describe('on the Object types catalogue', () => {
  beforeEach(() => {
    answer = () => new Promise(() => {})
  })

  const schema = { Customer: { display_name: 'Customer', fields: { name: { type: 'data', readable: true } } } }

  async function open() {
    const { default: SchemaPanel } = await import('./SchemaPanel')
    render(
      <MemoryRouter initialEntries={['/schema?tab=object-types']}>
        <SchemaPanel visibleSchema={schema as never} username="alice" onSessionExpired={() => {}} />
      </MemoryRouter>,
    )
  }

  it('shows the section on the card for someone the route answers', async () => {
    answer = () => Promise.resolve({ Customer: CUSTOMER })
    await open()

    fireEvent.click(await screen.findByText('Who can see this'))
    expect(screen.getByText(/only when their region matches/)).toBeInTheDocument()
  })

  it('shows nothing at all to someone it refuses', async () => {
    let refuse: (reason: Error) => void = () => {}
    answer = () => new Promise((_, reject) => (refuse = reject))
    await open()

    // SETTLED INSIDE act(), so the refusal is handled before the test
    // ends rather than landing after it.
    await act(async () => refuse(new Error('Not authorized to manage roles')))
    expect(screen.getByText('Customer')).toBeInTheDocument()
    expect(screen.queryByText('Who can see this')).not.toBeInTheDocument()
  })
})
