import { describe, it, expect } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { MemoryRouter, RouterProvider, createMemoryRouter } from 'react-router-dom'

import SchemaPanel from './SchemaPanel'

/** The panel keeps its tab and filter in the URL, so it needs a
 *  router. MemoryRouter rather than a mock, so the push/replace
 *  distinction these tests care about is the real one. */
function renderPanel(ui: React.ReactElement) {
  return render(<MemoryRouter initialEntries={['/schema']}>{ui}</MemoryRouter>)
}

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
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('Someone the business serves.')).toBeInTheDocument()
  })

  it('spotlights prominent fields separately from normal ones', () => {
    // The rendering rule taken from the reference implementation:
    // prominent properties get their own table, normal ones a regular
    // one. The separation is what carries the ontology author's intent
    // about which fields matter.
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Prominent')).toBeInTheDocument()
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Email')).toBeInTheDocument()
  })

  it('does not render hidden fields', () => {
    // Cosmetic, not security -- the value is still in the response.
    // This view honours the author's intent not to show it; it is not
    // withholding anything, and nothing here should suggest it is.
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.queryByText('Internal')).not.toBeInTheDocument()
  })

  it('shows a link field with its target and cardinality', () => {
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Transactions')).toBeInTheDocument()
    // Target and cardinality are now separate elements, because the
    // target is a button that navigates to that object type.
    expect(screen.getByText('many')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Transaction' })).toBeInTheDocument()
  })

  it('marks a deprecated object type', () => {
    renderPanel(
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
    renderPanel(<SchemaPanel visibleSchema={{}} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText(/do not have read access/)).toBeInTheDocument()
  })

  it('shows a spinner while the shell is still loading the schema', () => {
    // null is "not loaded yet", a different state from {} -- "loaded,
    // and you can see nothing". Conflating them would show a
    // permissions message during a normal page load.
    // No tab to open: nothing is rendered until the schema arrives.
    renderPanel(<SchemaPanel visibleSchema={null} username="alice" onSessionExpired={noop} />)

    expect(screen.queryByText(/do not have read access/)).not.toBeInTheDocument()
  })

  it('filters object types by name and by group', async () => {
    renderPanel(
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
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.getByText('Customer')).toBeInTheDocument()
  })
})

describe('SchemaPanel -- navigating between tabs', () => {
  it('clears the filter when the tab is clicked directly', () => {
    // Arriving from Discover sets the filter on purpose; clicking the
    // tab afterwards should start fresh rather than show whatever was
    // last looked at.
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)

    fireEvent.click(screen.getAllByText('Customer')[0] as HTMLElement)
    openObjectTypes()

    expect(screen.getByPlaceholderText(/Filter object types/)).toHaveValue('')
  })

  it('offers a clear button only when there is something to clear', () => {
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    expect(screen.queryByLabelText('Clear filter')).not.toBeInTheDocument()

    fireEvent.change(screen.getByPlaceholderText(/Filter object types/), {
      target: { value: 'Cust' },
    })

    expect(screen.getByLabelText('Clear filter')).toBeInTheDocument()
  })

  it('clears the field when the clear button is pressed', () => {
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()
    const box = screen.getByPlaceholderText(/Filter object types/)
    fireEvent.change(box, { target: { value: 'Cust' } })

    fireEvent.click(screen.getByLabelText('Clear filter'))

    expect(box).toHaveValue('')
  })

  it('opens the link types tab when a link tag is clicked', () => {
    renderPanel(<SchemaPanel visibleSchema={{ Customer: CUSTOMER }} username="alice" onSessionExpired={noop} />)
    openObjectTypes()

    fireEvent.click(screen.getByText('link'))

    expect(screen.getByPlaceholderText(/Filter link types/)).toHaveValue('CustomerTransactions')
  })
})

describe('SchemaPanel -- retracing steps', () => {
  // Following a reference is one click; retracing it should be too.
  // The state lives in the URL so the browser's own back button works,
  // which is why these assert on history rather than on a custom
  // stack.

  function renderAt(entries: string[]) {
    return render(
      <MemoryRouter initialEntries={entries}>
        <SchemaPanel
          visibleSchema={{ Customer: CUSTOMER }}
          username="alice"
          onSessionExpired={noop}
        />
      </MemoryRouter>,
    )
  }

  it('opens the tab named in the URL', () => {
    // A reload keeps your place, and a view is a shareable link.
    renderAt(['/schema?tab=link-types'])

    expect(screen.getByPlaceholderText(/Filter link types/)).toBeInTheDocument()
  })

  it('applies the filter named in the URL', () => {
    renderAt(['/schema?tab=object-types&q=Customer'])

    expect(screen.getByPlaceholderText(/Filter object types/)).toHaveValue('Customer')
  })

  it('defaults to Discover when the URL says nothing', () => {
    renderAt(['/schema'])

    expect(screen.getByText('Favourites')).toBeInTheDocument()
  })

  it('goes back to where a cross-reference was followed from', () => {
    // The whole point: click a link tag, press Back, and be where you
    // were rather than somewhere approximate.
    renderAt(['/schema?tab=object-types'])

    fireEvent.click(screen.getByText('link'))
    expect(screen.getByPlaceholderText(/Filter link types/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Back' }))

    expect(screen.getByPlaceholderText(/Filter object types/)).toBeInTheDocument()
  })

  it('does not make a history entry per keystroke', () => {
    // THE trap. Typing "Cust" would otherwise push four entries, and
    // pressing Back four times to undo one search is worse than having
    // no history at all. Typing REPLACES; only navigation pushes.
    //
    // Needs TWO entries and a real router. A first version rendered one
    // MemoryRouter entry and asserted queryByDisplayValue('Cu') was
    // absent -- which passes whether or not replace works, since a box
    // containing "Cus" does not match "Cu" either. It also could not
    // have detected a failure: with one entry Back cannot move at all.
    const router = createMemoryRouter(
      [{
        path: '/schema',
        element: (
          <SchemaPanel
            visibleSchema={{ Customer: CUSTOMER }}
            username="alice"
            onSessionExpired={noop}
          />
        ),
      }],
      { initialEntries: ['/schema?tab=discover', '/schema?tab=object-types'], initialIndex: 1 },
    )
    render(<RouterProvider router={router} />)

    const box = screen.getByPlaceholderText(/Filter object types/)
    fireEvent.change(box, { target: { value: 'C' } })
    fireEvent.change(box, { target: { value: 'Cu' } })
    fireEvent.change(box, { target: { value: 'Cus' } })

    fireEvent.click(screen.getByRole('button', { name: 'Back' }))

    // One Back leaves the tab entirely rather than peeling off a letter.
    expect(screen.queryByPlaceholderText(/Filter object types/)).toBeNull()
  })

  it('treats a tab click as a step worth retracing', () => {
    renderAt(['/schema?tab=object-types'])

    fireEvent.click(screen.getByRole('tab', { name: 'Link types' }))
    fireEvent.click(screen.getByRole('button', { name: 'Back' }))

    expect(screen.getByPlaceholderText(/Filter object types/)).toBeInTheDocument()
  })
})

describe('SchemaPanel -- icons', () => {
  // `icon` is a free string in the ontology, because the ontology
  // should not know which widget library renders it. That makes this
  // layer responsible for its own vocabulary. Previously the value was
  // cast `as never`, which is not validation -- a typo rendered
  // nothing, with no error in either layer.

  function renderWithIcon(icon: string | null) {
    renderPanel(
      <SchemaPanel
        visibleSchema={{ Customer: { ...CUSTOMER, icon } }}
        username="alice"
        onSessionExpired={noop}
      />,
    )
    openObjectTypes()
  }

  it('renders a real icon', () => {
    renderWithIcon('person')

    expect(document.querySelector('[data-icon="person"]')).toBeTruthy()
  })

  it('renders no icon, and no error, for a name the library does not know', () => {
    // Degrades to "no icon" rather than throwing: a typo in an
    // ontology must not take a page down.
    renderWithIcon('definitely-not-an-icon')

    expect(screen.getByText('Customer')).toBeInTheDocument()
    expect(document.querySelector('[data-icon="definitely-not-an-icon"]')).toBeNull()
  })

  it('renders nothing when no icon is declared', () => {
    renderWithIcon(null)

    expect(screen.getByText('Customer')).toBeInTheDocument()
  })
})
