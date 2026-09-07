import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getVisibleActionTypes = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getVisibleActionTypes: () => getVisibleActionTypes() }
})

const ActionTypes = (await import('./ActionTypes')).default

const TRANSFER = {
  affected_object_types: ['Account'],
  parameters: {
    new_from_balance: {
      type: 'number', required: true,
      display_name: 'New source balance',
      description: 'The balance the source account should END with.',
    },
    from_account_id: { type: 'object_reference', object_type: 'Account', required: true },
  },
}

beforeEach(() => {
  getVisibleActionTypes.mockReset()
})

describe('ActionTypes', () => {
  it('shows a parameter with its type, requiredness and description', async () => {
    // The description is why this matters: "new_from_balance (number,
    // required)" does not say whether that is the resulting balance or
    // the amount to move. The ontology can now say, and this shows it.
    getVisibleActionTypes.mockResolvedValue({ TransferFunds: TRANSFER })

    render(<ActionTypes onSessionExpired={() => {}} />)

    expect(await screen.findByText('TransferFunds')).toBeInTheDocument()
    expect(screen.getByText('New source balance')).toBeInTheDocument()
    expect(screen.getByText(/should END with/)).toBeInTheDocument()
    expect(screen.getAllByText('required').length).toBeGreaterThan(0)
  })

  it('shows the API name only when it differs from the label', async () => {
    getVisibleActionTypes.mockResolvedValue({ TransferFunds: TRANSFER })

    render(<ActionTypes onSessionExpired={() => {}} />)

    await screen.findByText('TransferFunds')
    // Labelled parameter: both shown, since they differ.
    expect(screen.getByText('new_from_balance')).toBeInTheDocument()
    // Unlabelled: the API name IS the label, so it appears once.
    expect(screen.getAllByText('from_account_id')).toHaveLength(1)
  })

  it('names which object types an action affects', async () => {
    getVisibleActionTypes.mockResolvedValue({ TransferFunds: TRANSFER })

    render(<ActionTypes onSessionExpired={() => {}} />)

    expect(await screen.findByText(/affects Account/)).toBeInTheDocument()
  })

  it('says so plainly when the caller can execute nothing', async () => {
    // Filtered server-side: an action the caller cannot execute is
    // ABSENT, not disabled. Same uniform denial as everywhere else.
    getVisibleActionTypes.mockResolvedValue({})

    render(<ActionTypes onSessionExpired={() => {}} />)

    expect(await screen.findByText(/cannot execute any action/)).toBeInTheDocument()
  })

  it('surfaces the API error rather than replacing it', async () => {
    getVisibleActionTypes.mockRejectedValue(new Error('action types unavailable'))

    render(<ActionTypes onSessionExpired={() => {}} />)

    expect(await screen.findByText(/action types unavailable/)).toBeInTheDocument()
  })

  it('fetches once, not on every render', async () => {
    // The same bug the schema panel had: depending on
    // onSessionExpired, which the shell recreates each render.
    getVisibleActionTypes.mockResolvedValue({ TransferFunds: TRANSFER })

    const { rerender } = render(<ActionTypes onSessionExpired={() => {}} />)
    await screen.findByText('TransferFunds')
    rerender(<ActionTypes onSessionExpired={() => {}} />)
    rerender(<ActionTypes onSessionExpired={() => {}} />)

    expect(getVisibleActionTypes).toHaveBeenCalledTimes(1)
  })
})
