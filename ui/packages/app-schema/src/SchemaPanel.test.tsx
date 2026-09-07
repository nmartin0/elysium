import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'

const getMyVisibleSchema = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getMyVisibleSchema: () => getMyVisibleSchema() }
})

const SchemaPanel = (await import('./SchemaPanel')).default

const CUSTOMER = {
  display_name: 'Customer',
  plural_display_name: 'Customers',
  description: 'Someone the business serves.',
  icon: 'person',
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

beforeEach(() => {
  getMyVisibleSchema.mockReset()
})

describe('SchemaPanel', () => {
  it('renders an object type with its display name and description', async () => {
    getMyVisibleSchema.mockResolvedValue({ Customer: CUSTOMER })

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('Someone the business serves.')).toBeInTheDocument()
  })

  it('spotlights prominent fields separately from normal ones', async () => {
    // The rendering rule taken from the reference implementation:
    // prominent properties get their own table, normal ones a regular
    // one. Both are present; the separation is what carries the
    // ontology author's intent about which fields matter.
    getMyVisibleSchema.mockResolvedValue({ Customer: CUSTOMER })

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText('Prominent')).toBeInTheDocument()
    expect(screen.getByText('Name')).toBeInTheDocument()
    expect(screen.getByText('Email')).toBeInTheDocument()
  })

  it('does not render hidden fields', async () => {
    // Cosmetic, not security -- the value is still in the response.
    // This view honours the author's intent not to show it; it is not
    // withholding anything, and nothing here should suggest it is.
    getMyVisibleSchema.mockResolvedValue({ Customer: CUSTOMER })

    render(<SchemaPanel onSessionExpired={() => {}} />)

    await screen.findByText('Customer')
    expect(screen.queryByText('Internal')).not.toBeInTheDocument()
  })

  it('shows a link field with its target and cardinality', async () => {
    getMyVisibleSchema.mockResolvedValue({ Customer: CUSTOMER })

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText('Transactions')).toBeInTheDocument()
    expect(screen.getByText(/many Transaction/)).toBeInTheDocument()
  })

  it('marks a deprecated object type', async () => {
    getMyVisibleSchema.mockResolvedValue({
      Customer: { ...CUSTOMER, status: 'deprecated' },
    })

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText('deprecated')).toBeInTheDocument()
  })

  it('says so plainly when the caller can see nothing', async () => {
    // A user with no read: grants gets an empty ontology rather than a
    // forbidden page -- the same uniform denial every read path uses.
    // Rendering nothing at all would look like a loading failure.
    getMyVisibleSchema.mockResolvedValue({})

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText(/do not have read access/)).toBeInTheDocument()
  })

  it('filters object types by name and by group', async () => {
    getMyVisibleSchema.mockResolvedValue({
      Customer: CUSTOMER,
      Widget: { ...CUSTOMER, display_name: 'Widget', group: 'Inventory', fields: {} },
    })

    render(<SchemaPanel onSessionExpired={() => {}} />)
    await screen.findByText('Customer')

    fireEvent.change(screen.getByPlaceholderText(/Filter object types/), {
      target: { value: 'Inventory' },
    })

    await waitFor(() => {
      expect(screen.queryByText('Customer')).not.toBeInTheDocument()
    })
    expect(screen.getByText('Widget')).toBeInTheDocument()
  })

  it('surfaces the API error rather than replacing it', async () => {
    // The backend writes real messages -- an unknown aggregate names
    // the valid ones. Swallowing them for a generic failure throws
    // away the useful half.
    getMyVisibleSchema.mockRejectedValue(new Error('ontology unavailable'))

    render(<SchemaPanel onSessionExpired={() => {}} />)

    expect(await screen.findByText(/ontology unavailable/)).toBeInTheDocument()
  })

  it('reports an expired session upward rather than showing an error', async () => {
    const onSessionExpired = vi.fn()
    // A real ApiError, not a plain Error with a status bolted on:
    // handleIfSessionExpired checks the TYPE, so a look-alike would
    // pass this test while failing in the browser.
    const { ApiError } = await import('@elysium/shell-api/api')
    getMyVisibleSchema.mockRejectedValue(new ApiError(401, 'Unauthorized'))

    render(<SchemaPanel onSessionExpired={onSessionExpired} />)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalled())
  })
})

describe('SchemaPanel -- fetching', () => {
  it('fetches the schema once, not on every render', async () => {
    // Found in a real server log, not by any test: one page load
    // produced THREE GET /me/visible-schema calls. The effect depended
    // on onSessionExpired, which the shell declares as a plain
    // function -- a new object every render, so the effect re-ran.
    //
    // Invisible in the browser: the page looked correct and simply did
    // three times the work. On a large ontology that is three full
    // schema serialisations per render.
    getMyVisibleSchema.mockResolvedValue({ Customer: CUSTOMER })

    const { rerender } = render(<SchemaPanel onSessionExpired={() => {}} />)
    await screen.findByText('Customer')

    // A NEW handler each time, exactly as the shell provides.
    rerender(<SchemaPanel onSessionExpired={() => {}} />)
    rerender(<SchemaPanel onSessionExpired={() => {}} />)

    expect(getMyVisibleSchema).toHaveBeenCalledTimes(1)
  })
})
