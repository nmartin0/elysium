import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'

const getSilos = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getSilos: () => getSilos() }
})

const { default: Silos } = await import('./Silos')

const HEALTHY = [
  {
    name: 'primary_sql',
    adapter: 'sqlite',
    object_types: ['Customer'],
    reachable: true,
    failure: null,
    fields: [
      { object_type: 'Customer', field: 'name', column: 'name', table: 'customers', is_identifier: false },
      { object_type: 'Customer', field: 'customer_id', column: 'customer_id', table: 'customers', is_identifier: true },
    ],
  },
  {
    name: 'support_crm',
    adapter: 'sqlite',
    object_types: ['Ticket'],
    reachable: true,
    failure: null,
    fields: [
      { object_type: 'Ticket', field: 'risk_score', column: 'score_val', table: 'customer_risk', is_identifier: false },
      { object_type: 'Ticket', field: 'customer_id', column: 'cust_ref', table: 'customer_risk', is_identifier: true },
    ],
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  getSilos.mockResolvedValue(HEALTHY)
})

describe('Silos', () => {
  it('answers "is anything wrong" before listing anything', async () => {
    // A table of green rows makes you read every one to find that out.
    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText(/All 2 silos are reachable/)).toBeInTheDocument()
  })

  it('names what is not answering', async () => {
    getSilos.mockResolvedValue([HEALTHY[0], { ...HEALTHY[1], reachable: false, failure: 'FileNotFoundError' }])

    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText(/not answering/)).toBeInTheDocument()
    expect(screen.getByText('FileNotFoundError')).toBeInTheDocument()
  })

  it('shows which object types each silo backs', async () => {
    // The operational question when one is down: what stops working.
    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText('Customer')).toBeInTheDocument()
    expect(screen.getByText('Ticket')).toBeInTheDocument()
  })

  it('reports a failure rather than an empty screen', async () => {
    getSilos.mockRejectedValue(new Error('silos unavailable'))

    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText(/silos unavailable/)).toBeInTheDocument()
  })
})

describe('Silos -- the fields behind a silo', () => {
  it('hides field detail until asked', async () => {
    // A silo list is read to answer "is anything wrong". Field detail
    // is the follow-up question, and showing it always would bury the
    // answer to the first one.
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')

    expect(screen.queryByText('customers')).not.toBeInTheDocument()
  })

  it('shows the physical table and column on expand', async () => {
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')

    fireEvent.click(screen.getByLabelText(/Show fields backed by primary_sql/))

    // getAllByText: the identifier row shares the table name, which is
    // correct -- both live in `customers`.
    // Both getAllByText: a field name can equal its column name (name
    // -> name), and the identifier row shares the table, so single
    // queries find several. The assertion is that the detail appeared.
    expect(screen.getAllByText('customers').length).toBeGreaterThan(0)
    expect(screen.getAllByText('name').length).toBeGreaterThan(0)
  })

  it('marks a column whose name differs from its field', async () => {
    /**
     * The case worth noticing. Customer.risk_score reads a column
     * called score_val, and when a query returns something unexpected
     * that mismatch is exactly what you are looking for -- so it is
     * marked rather than left to be spotted by comparing two columns.
     */
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('support_crm')

    fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))

    expect(screen.getByText('score_val')).toBeInTheDocument()
    // Two renamings in this silo now -- score_val and cust_ref -- so
    // the assertion is that renaming is marked at all, not that it
    // happens once.
    expect(screen.getAllByText(/renamed/).length).toBeGreaterThan(0)
  })

  it('collapses again', async () => {
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')
    fireEvent.click(screen.getByLabelText(/Show fields backed by primary_sql/))

    fireEvent.click(screen.getByLabelText(/Hide fields backed by primary_sql/))

    expect(screen.queryByText('customers')).not.toBeInTheDocument()
  })
})

describe('Silos -- the join key', () => {
  it('marks the identifier and shows its renaming', async () => {
    /**
     * The mismatch that matters more than a renamed data column: a
     * wrong join key returns NOTHING, or another object's row, rather
     * than a wrong value.
     */
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('support_crm')

    fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))

    expect(screen.getByText('identifier')).toBeInTheDocument()
    expect(screen.getByText('cust_ref')).toBeInTheDocument()
  })

  it('separates the tag from the field name in the TEXT, not just visually', () => {
    /**
     * A CSS margin separates them on screen and leaves the DOM text as
     * "customer_ididentifier" -- which is what a screen reader
     * announces and what a copy-paste produces. Found in a paste of
     * the real screen.
     */
    render(<Silos onSessionExpired={() => {}} />)

    return screen.findByText('support_crm').then(() => {
      fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))
      const cell = screen.getByText('identifier').closest('td')
      expect(cell?.textContent).not.toMatch(/customer_ididentifier/)
      expect(cell?.textContent).toMatch(/customer_id identifier/)
    })
  })
})
