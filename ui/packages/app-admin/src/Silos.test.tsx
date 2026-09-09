import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getSilos = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getSilos: () => getSilos() }
})

const { default: Silos } = await import('./Silos')

const HEALTHY = [
  { name: 'primary_sql', adapter: 'sqlite', object_types: ['Customer'], reachable: true, failure: null },
  { name: 'support_crm', adapter: 'sqlite', object_types: ['Ticket'], reachable: true, failure: null },
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
