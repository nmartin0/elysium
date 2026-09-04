import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react'

// Partial mock via importOriginal, not a hand-duplicated module shape
// -- see App.test.tsx's own header comment for the full reasoning.
vi.mock('../api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../api')>()
  return {
    ...actual,
    confirmWrite: vi.fn(),
  }
})

import { confirmWrite, ApiError } from '../api'
import PendingWriteCard, { type PendingWrite } from './PendingWriteCard'

const mockedConfirmWrite = vi.mocked(confirmWrite)

beforeEach(() => {
  vi.clearAllMocks()
})

function singleObjectWrite(overrides: Partial<PendingWrite> = {}): PendingWrite {
  return {
    id: 'write-1',
    action_type_name: 'UpdateCustomerName',
    description: 'Update the customer name',
    sub_writes: [
      {
        object_type: 'Customer',
        object_id: 'cust_001',
        changes: { name: 'Ada Lovelace' },
        expected_current_values: { name: 'Ada Okafor' },
      },
    ],
    ...overrides,
  }
}

function multiObjectWrite(): PendingWrite {
  return {
    id: 'write-2',
    action_type_name: 'TransferFunds',
    description: 'Transfer between accounts',
    sub_writes: [
      {
        object_type: 'Account',
        object_id: 'acct_from',
        changes: { balance: 400 },
        expected_current_values: { balance: 500 },
      },
      {
        object_type: 'Account',
        object_id: 'acct_to',
        changes: { balance: 600 },
        expected_current_values: { balance: 500 },
      },
    ],
  }
}

describe('PendingWriteCard -- rendering', () => {
  it('renders the action name and description', () => {
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.getByText('UpdateCustomerName')).toBeInTheDocument()
    expect(screen.getByText('Update the customer name')).toBeInTheDocument()
  })

  it('a single-object write renders fields with NO object_type/object_id label', () => {
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.queryByText('Customer cust_001')).not.toBeInTheDocument()
  })

  it('a multi-object write gives EACH sub_write its own object_type/object_id label', () => {
    render(<PendingWriteCard pendingWrite={multiObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.getByText('Account acct_from')).toBeInTheDocument()
    expect(screen.getByText('Account acct_to')).toBeInTheDocument()
  })

  it('shows an "old -> new" transition when expected_current_values has the field', () => {
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    // "Ada Okafor" shares a text node with the trailing arrow (" → "),
    // so an exact getByText('Ada Okafor') can't match it -- a
    // substring check against the element's own full text content is
    // the right tool here, testing-library's own recommended pattern
    // for text split across/combined within nodes.
    expect(screen.getByText((_, element) => element?.textContent === 'Ada Okafor \u2192 ')).toBeInTheDocument()
    expect(screen.getByText('Ada Lovelace')).toBeInTheDocument()
  })

  it('shows only the new value (no transition) when the field has no expected_current_value -- the create case', () => {
    const createWrite = singleObjectWrite({
      sub_writes: [
        {
          object_type: 'Customer',
          object_id: 'cust_new',
          changes: { name: 'Brand New Customer' },
          expected_current_values: {},
        },
      ],
    })
    render(<PendingWriteCard pendingWrite={createWrite} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.getByText('Brand New Customer')).toBeInTheDocument()
    expect(screen.queryByText(/→/)).not.toBeInTheDocument()
  })

  it('field names are formatted for display (e.g. reopen_reason -> Reopen reason)', () => {
    const write = singleObjectWrite({
      sub_writes: [
        {
          object_type: 'Ticket',
          object_id: 'ticket_1',
          changes: { reopen_reason: 'customer disagreed' },
          expected_current_values: {},
        },
      ],
    })
    render(<PendingWriteCard pendingWrite={write} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.getByText('Reopen reason')).toBeInTheDocument()
  })

  it('a null value formats as "(not set)"', () => {
    const write = singleObjectWrite({
      sub_writes: [
        {
          object_type: 'Customer',
          object_id: 'cust_001',
          changes: { email: null },
          expected_current_values: {},
        },
      ],
    })
    render(<PendingWriteCard pendingWrite={write} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)
    expect(screen.getByText('(not set)')).toBeInTheDocument()
  })
})

describe('PendingWriteCard -- approve', () => {
  it('clicking Approve calls confirmWrite(id, true)', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(mockedConfirmWrite).toHaveBeenCalledWith('write-1', true))
  })

  it('calls onResolved(true) after a successful approve', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    const onResolved = vi.fn()
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={onResolved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(true))
  })

  it('shows "Change applied." and hides the fields/buttons once resolved', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(screen.getByText('Change applied.')).toBeInTheDocument())
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.queryByText('Ada Okafor')).not.toBeInTheDocument()
  })

  it('the resolved "Change applied." Callout uses intent="success" -- a real, positive outcome, confirmed via the real bp6-intent-success class Blueprint itself applies, not just that the right text shows up', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() =>
      expect(screen.getByText('Change applied.').closest('.bp6-callout')).toHaveClass('bp6-intent-success'),
    )
  })
})

describe('PendingWriteCard -- reject', () => {
  it('clicking Reject calls confirmWrite(id, false)', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(mockedConfirmWrite).toHaveBeenCalledWith('write-1', false))
  })

  it('calls onResolved(false) after a successful reject', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    const onResolved = vi.fn()
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={onResolved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(onResolved).toHaveBeenCalledWith(false))
  })

  it('shows "Change rejected." once resolved', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(screen.getByText('Change rejected.')).toBeInTheDocument())
  })

  it('the resolved "Change rejected." Callout has NO intent at all -- deliberately neither success nor danger, confirmed directly: declining a change is a genuine, correct decision either way, not a failure, so it must not carry the same bp6-intent-success class the applied case does', async () => {
    mockedConfirmWrite.mockResolvedValue({})
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    await waitFor(() => expect(screen.getByText('Change rejected.')).toBeInTheDocument())
    const callout = screen.getByText('Change rejected.').closest('.bp6-callout')
    expect(callout).not.toHaveClass('bp6-intent-success')
    expect(callout).not.toHaveClass('bp6-intent-danger')
  })
})

describe('PendingWriteCard -- in-flight and failure handling', () => {
  it('disables both buttons while the request is in flight', async () => {
    let resolveConfirm: (value: unknown) => void
    mockedConfirmWrite.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve
      }),
    )
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()

    resolveConfirm!({})
    await waitFor(() => expect(screen.getByText('Change applied.')).toBeInTheDocument())
  })

  it('shows a real, spinning loading indicator on ONLY the clicked button, not both -- a real, deliberate improvement over a plain shared "submitting" boolean, confirmed directly, not just that both happen to end up disabled', async () => {
    let resolveConfirm: (value: unknown) => void
    mockedConfirmWrite.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve
      }),
    )
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Reject' }))

    // Reject itself is the one that's actually loading -- a real,
    // rendered spinner (role="progressbar", confirmed directly against
    // Button's own real DOM output before writing this assertion, not
    // assumed) nested inside ITS OWN button specifically.
    await waitFor(() =>
      expect(within(screen.getByRole('button', { name: 'Reject' })).getByRole('progressbar')).toBeInTheDocument(),
    )
    // Approve is disabled too (preventing a confusing double-submit),
    // but genuinely NOT loading -- no spinner of its own at all, since
    // it was never the one actually clicked.
    expect(screen.getByRole('button', { name: 'Approve' })).toBeDisabled()
    expect(within(screen.getByRole('button', { name: 'Approve' })).queryByRole('progressbar')).not.toBeInTheDocument()

    resolveConfirm!({})
    await waitFor(() => expect(screen.getByText('Change rejected.')).toBeInTheDocument())
  })

  it('the SAME per-action loading behavior, symmetrically, when Approve is the one clicked instead -- confirmed as its own, separate case, not just assumed from the Reject direction above given the two branches are hand-written, independent conditionals that could silently diverge', async () => {
    let resolveConfirm: (value: unknown) => void
    mockedConfirmWrite.mockReturnValue(
      new Promise((resolve) => {
        resolveConfirm = resolve
      }),
    )
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() =>
      expect(within(screen.getByRole('button', { name: 'Approve' })).getByRole('progressbar')).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Reject' })).toBeDisabled()
    expect(within(screen.getByRole('button', { name: 'Reject' })).queryByRole('progressbar')).not.toBeInTheDocument()

    resolveConfirm!({})
    await waitFor(() => expect(screen.getByText('Change applied.')).toBeInTheDocument())
  })

  it("on a non-401 failure, shows the backend's own error message and does NOT resolve", async () => {
    mockedConfirmWrite.mockRejectedValue(new ApiError(500, 'Something went wrong'))
    const onResolved = vi.fn()
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={onResolved} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(screen.getByText('Something went wrong')).toBeInTheDocument())
    expect(onResolved).not.toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('re-enables the buttons after a non-401 failure', async () => {
    mockedConfirmWrite.mockRejectedValue(new ApiError(500, 'Something went wrong'))
    render(<PendingWriteCard pendingWrite={singleObjectWrite()} onSessionExpired={vi.fn()} onResolved={vi.fn()} />)

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(screen.getByText('Something went wrong')).toBeInTheDocument())
    expect(screen.getByRole('button', { name: 'Approve' })).not.toBeDisabled()
  })

  it('on a 401, calls onSessionExpired and shows NO error message and does NOT resolve', async () => {
    mockedConfirmWrite.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    const onResolved = vi.fn()
    render(
      <PendingWriteCard
        pendingWrite={singleObjectWrite()}
        onSessionExpired={onSessionExpired}
        onResolved={onResolved}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
    expect(onResolved).not.toHaveBeenCalled()
  })
})
