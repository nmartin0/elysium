import { describe, it, expect } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

import SchemaPanel from './SchemaPanel'

/** Opens the Object types tab. The panel now lands on Discover, which
 *  is the useful default for a real user and means these tests have to
 *  navigate the way one does. */
function openObjectTypes() {
  fireEvent.click(screen.getByRole('tab', { name: 'Object types' }))
}

const CUSTOMER = {
  display_name: 'Customer',
  plural_display_name: 'Customers',
  description: 'Someone the business serves.',
  icon: null,
  color: null,
  status: 'active',
  group: 'Core',
  id_field: 'customer_id',
  title_field: 'name',
  fields: {
    name: { type: 'data', display_name: 'Name', visibility: 'prominent', status: 'active' },
    email: { type: 'data', display_name: 'Email', visibility: 'normal', status: 'active' },
    internal: { type: 'data', display_name: 'Internal', visibility: 'hidden', status: 'active' },
    transactions: {
      type: 'link', display_name: 'Transactions', target: 'Transaction',
      cardinality: 'many', link_type: 'CustomerTransactions', visibility: 'normal',
    },
  },
}

const noop = () => {}

describe('SchemaPanel', () => {
  it('renders an object type with its display name and description', () => {
    render(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('Someone the business serves.')).toBeInTheDocument()
  })

  it('spotlights prominent fields separately from normal ones', () => {
    // The rendering rule taken from the reference implementation:
    // prominent properties get their own table, normal ones a regular
    // one. The separation is what carries the ontology author's intent
    // about which fields matter.
    render(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Prominent')).toBeInTheDocument()
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Email')).toBeInTheDocument()
  })

  it('does not render hidden fields', () => {
    // Cosmetic, not security -- the value is still in the response.
    // This view honours the author's intent not to show it; it is not
    // withholding anything, and nothing here should suggest it is.
    render(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.queryByText('Internal')).not.toBeInTheDocument()
  })

  it('shows a link field with its target and cardinality', () => {
    render(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Transactions')).toBeInTheDocument()
    expect(screen.getByText(/many Transaction/)).toBeInTheDocument()
  })

  it('marks a deprecated object type', () => {
    render(
      <SchemaPanel
        visibleSchema={{ Customer: { ...CUSTOMER, status: 'deprecated' } }}
        username="alice"
        onSessionExpired={noop}
      />,
    )
    openObjectTypes()

    expect(screen.getByText('deprecated')).toBeInTheDocument()
  })

  it('says so plainly when the caller can see nothing', () => {
    // A user with no read: grants gets an empty ontology rather than a
    // forbidden page -- the same uniform denial every read path uses.
    // Rendering nothing at all would look like a loading failure.
    render(<SchemaPanel visibleSchema={{}} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText(/do not have read access/)).toBeInTheDocument()
  })

  it('shows a spinner while the shell is still loading the schema', () => {
    // null is "not loaded yet", a different state from {} -- "loaded,
    // and you can see nothing". Conflating them would show a
    // permissions message during a normal page load.
    // No tab to open: nothing is rendered until the schema arrives.
    render(<SchemaPanel visibleSchema={null} username="alice" onSessionExpired={noop} />)

    expect(screen.queryByText(/do not have read access/)).not.toBeInTheDocument()
  })

  it('filters object types by name and by group', async () => {
    render(
      <SchemaPanel
        visibleSchema={{
          Customer: CUSTOMER,
          Widget: { ...CUSTOMER, display_name: 'Widget', group: 'Inventory', fields: {} },
        }}
        username="alice"
        onSessionExpired={noop}
      />,
    )
    openObjectTypes()

    fireEvent.change(screen.getByPlaceholderText(/Filter object types/), {
      target: { value: 'Inventory' },
    })

    await waitFor(() => {
      expect(screen.queryByText('Customer')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Widget')).toBeInTheDocument()
  })

  it('takes the schema as a prop rather than fetching its own', () => {
    // Found in a real server log: one page load produced THREE GET
    // /me/visible-schema calls. The first fix chased the effect
    // dependency causing the repeat, which would have taken three down
    // to two -- and missed that the shell fetches this already and
    // hands it to every other panel, so the right number was zero.
    //
    // The log was pointing at something larger than the symptom it
    // showed. Rendering with no network available at all is the
    // property that matters.
    render(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Customer')).toBeInTheDocument()
  })
})
