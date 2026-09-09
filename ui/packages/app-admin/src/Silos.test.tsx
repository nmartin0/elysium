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
    name: 'primary_sql', adapter: 'sqlite', object_types: ['Customer'],
    reachable: true, failure: null,
    fields: [{ object_type: 'Customer', field: 'name', column: 'name', table: 'customers' }],
  },
  {
    name: 'support_crm', adapter: 'sqlite', object_types: ['Ticket'],
    reachable: true, failure: null,
    fields: [{ object_type: 'Ticket', field: 'risk_score', column: 'score_val', table: 'customer_risk' }],
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
    getSilos.mockResolvedValue([
      HEALTHY[0],
      { ...HEALTHY[1], reachable: false, failure: 'FileNotFoundError' },
    ])

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

    expect(screen.getByText('customers')).toBeInTheDocument()
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
    expect(screen.getByText(/renamed/)).toBeInTheDocument()
  })

  it('collapses again', async () => {
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')
    fireEvent.click(screen.getByLabelText(/Show fields backed by primary_sql/))

    fireEvent.click(screen.getByLabelText(/Hide fields backed by primary_sql/))

    expect(screen.queryByText('customers')).not.toBeInTheDocument()
  })
})
