import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', () => {
  class ApiError extends Error {
    constructor(status, message) {
      super(message)
      this.status = status
    }
  }
  return {
    proposeAction: vi.fn(),
    ApiError,
    handleIfSessionExpired: (err, onSessionExpired) => {
      if (err instanceof ApiError && err.status === 401) {
        onSessionExpired()
        return true
      }
      return false
    },
  }
})
vi.mock('@elysium/shell-api/components/PendingWriteCard', () => ({
  // A simple stub -- PendingWriteCard has its own, thorough, direct
  // test file. This file's own job is only to confirm ActionForm
  // renders it with the right pendingWrite/onResolved once a propose
  // succeeds, not to re-prove its own internal behavior again here.
  default: ({ pendingWrite, onResolved }) => (
    <div data-testid="pending-write-card">
      <p>{pendingWrite.id}</p>
      <button onClick={onResolved}>fake resolve</button>
    </div>
  ),
}))

import { proposeAction, ApiError } from '@elysium/shell-api/api'
import ActionForm from './ActionForm'

function updateCustomerNameDef() {
  return {
    parameters: {
      customer_id: { type: 'object_reference', object_type: 'Customer', required: true },
      new_name: { type: 'string', required: true },
    },
  }
}

function transferFundsDef() {
  // Matches tests/integration/fixtures/ontology_schema.yaml's own
  // REAL TransferFunds definition exactly -- from_account_id and
  // to_account_id both declare object_type: Account (the real bug
  // this file separately, explicitly documents), and there is no
  // single "amount" parameter at all -- two separate balance targets,
  // new_from_balance and new_to_balance.
  return {
    parameters: {
      from_account_id: { type: 'object_reference', object_type: 'Account', required: true },
      to_account_id: { type: 'object_reference', object_type: 'Account', required: true },
      new_from_balance: { type: 'number', required: true },
      new_to_balance: { type: 'number', required: true },
    },
  }
}

function renderForm(overrides = {}) {
  const props = {
    actionName: 'UpdateCustomerName',
    actionDef: updateCustomerNameDef(),
    objectType: 'Customer',
    objectId: 'cust_001',
    onCancel: vi.fn(),
    onResolved: vi.fn(),
    onSessionExpired: vi.fn(),
    ...overrides,
  }
  return { ...render(<ActionForm {...props} />), props }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ActionForm -- rendering', () => {
  it('renders the action name and one labeled input per parameter', () => {
    renderForm()
    expect(screen.getByText('UpdateCustomerName')).toBeInTheDocument()
    expect(screen.getByLabelText('Customer id')).toBeInTheDocument()
    expect(screen.getByLabelText('New name')).toBeInTheDocument()
  })

  it('pre-fills and DISABLES the object_reference parameter matching the current object', () => {
    renderForm()
    const input = screen.getByLabelText('Customer id')
    expect(input).toHaveValue('cust_001')
    expect(input).toBeDisabled()
  })

  it('leaves an object_reference parameter for a DIFFERENT object type empty and editable', () => {
    // A synthetic action def, deliberately -- the real TransferFunds
    // has BOTH its own account references sharing object_type:
    // Account, which this test file separately, explicitly documents
    // as a real, discovered bug (see the "real TransferFunds bug"
    // test below). This one exists to confirm the LOCKING mechanism
    // itself works correctly when a parameter's own object_type
    // genuinely, correctly differs from the current page's.
    const actionDef = {
      parameters: {
        customer_id: { type: 'object_reference', object_type: 'Customer', required: true },
        linked_account_id: { type: 'object_reference', object_type: 'Account', required: true },
      },
    }
    renderForm({ actionName: 'SyntheticAction', actionDef, objectType: 'Customer', objectId: 'cust_001' })

    // customer_id matches the current object (Customer) -- locked.
    expect(screen.getByLabelText('Customer id')).toHaveValue('cust_001')
    expect(screen.getByLabelText('Customer id')).toBeDisabled()
    // linked_account_id is a genuinely different type (Account) --
    // not locked, empty.
    expect(screen.getByLabelText('Linked account id')).toHaveValue('')
    expect(screen.getByLabelText('Linked account id')).not.toBeDisabled()
  })

  it('REAL BUG, documented directly: the actual TransferFunds shape locks BOTH account fields to the SAME value, since neither the id nor the render logic distinguishes which object_reference parameter is "the one matching this page" beyond object_type equality alone', () => {
    // Confirmed directly against tests/integration/fixtures/
    // ontology_schema.yaml's own real TransferFunds definition: both
    // from_account_id and to_account_id declare object_type: Account.
    // ActionForm's own isLockedToCurrentObject check (paramSpec.type
    // === 'object_reference' && paramSpec.object_type === objectType)
    // has no way to tell them apart -- it locks EVERY object_reference
    // parameter whose type matches, not just the one the person
    // actually navigated here from. The real, practical consequence:
    // opening TransferFunds from an Account's own page pre-fills BOTH
    // fields with THAT account's id and disables both -- there is
    // currently no way to actually specify a DIFFERENT "to" account
    // through this form at all. A real, previously undiscovered
    // functional bug, surfaced directly by writing this test suite --
    // not fixed here (a real design decision is needed for the right
    // fix: track which SPECIFIC parameter the object was navigated
    // from, not just type-match every parameter of the same type),
    // but documented honestly rather than silently worked around.
    renderForm({
      actionName: 'TransferFunds',
      actionDef: transferFundsDef(),
      objectType: 'Account',
      objectId: 'acct_from',
    })

    expect(screen.getByLabelText('From account id')).toHaveValue('acct_from')
    expect(screen.getByLabelText('From account id')).toBeDisabled()
    // This SHOULD be empty and editable (a different account) -- it
    // is not. Asserting the REAL, current (buggy) behavior here,
    // deliberately, so this test starts FAILING the moment someone
    // fixes it -- a visible, honest signal to update this test (and
    // its own comment) rather than the bug silently persisting
    // unnoticed forever.
    expect(screen.getByLabelText('To account id')).toHaveValue('acct_from')
    expect(screen.getByLabelText('To account id')).toBeDisabled()
  })

  it('renders a "number" parameter as a real number input', () => {
    renderForm({ actionName: 'TransferFunds', actionDef: transferFundsDef(), objectType: 'Account', objectId: 'acct_from' })
    expect(screen.getByLabelText('New from balance')).toHaveAttribute('type', 'number')
  })

  it('renders a non-number parameter as a plain text input', () => {
    renderForm()
    expect(screen.getByLabelText('New name')).toHaveAttribute('type', 'text')
  })

  it('marks a required parameter as required', () => {
    renderForm()
    expect(screen.getByLabelText('New name')).toBeRequired()
  })
})

describe('ActionForm -- editing', () => {
  it('typing updates only that specific field, leaving others untouched', () => {
    renderForm({ actionName: 'TransferFunds', actionDef: transferFundsDef(), objectType: 'Account', objectId: 'acct_from' })

    fireEvent.change(screen.getByLabelText('New from balance'), { target: { value: '250' } })

    expect(screen.getByLabelText('New from balance')).toHaveValue(250)
    // New_to_balance, a completely separate field, is untouched.
    expect(screen.getByLabelText('New to balance')).toHaveValue(null)
    // The locked field is untouched too, still showing the current object.
    expect(screen.getByLabelText('From account id')).toHaveValue('acct_from')
  })
})

describe('ActionForm -- submitting', () => {
  it('calls proposeAction with the real, current field values', async () => {
    proposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() =>
      expect(proposeAction).toHaveBeenCalledWith('UpdateCustomerName', {
        customer_id: 'cust_001',
        new_name: 'Ada Lovelace',
      })
    )
  })

  it('coerces a "number" parameter\'s string value to a real JSON number', async () => {
    proposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm({ actionName: 'TransferFunds', actionDef: transferFundsDef(), objectType: 'Account', objectId: 'acct_from' })

    fireEvent.change(screen.getByLabelText('New from balance'), { target: { value: '250' } })
    fireEvent.change(screen.getByLabelText('New to balance'), { target: { value: '750' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() =>
      expect(proposeAction).toHaveBeenCalledWith('TransferFunds', {
        // Both locked to the same value -- the real, documented bug,
        // reflected honestly here too, not glossed over.
        from_account_id: 'acct_from',
        to_account_id: 'acct_from',
        new_from_balance: 250,
        new_to_balance: 750,
      })
    )
    // Real numbers, not the strings "250"/"750".
    expect(typeof proposeAction.mock.calls[0][1].new_from_balance).toBe('number')
    expect(typeof proposeAction.mock.calls[0][1].new_to_balance).toBe('number')
  })

  it('leaves an empty, non-required "number" parameter as an empty string, not coerced to 0 or NaN', async () => {
    // A synthetic, deliberately non-required number parameter --
    // every real number parameter in this project's own actual
    // schemas is required (confirmed directly, not assumed), and a
    // required, empty field never reaches handleSubmit at all (the
    // browser's own native validation blocks the submit event itself
    // first) -- this is the only way to genuinely exercise this
    // component's own `raw !== ''` coercion guard at all.
    const actionDef = {
      parameters: { optional_amount: { type: 'number', required: false } },
    }
    proposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm({ actionName: 'SyntheticAction', actionDef, objectType: 'Customer', objectId: 'cust_001' })

    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(proposeAction).toHaveBeenCalled())
    expect(proposeAction.mock.calls[0][1].optional_amount).toBe('')
  })

  it('disables both Propose and Cancel while the request is in flight', async () => {
    proposeAction.mockReturnValue(new Promise(() => {}))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Propose' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
})

describe('ActionForm -- a successful propose', () => {
  it('shows PendingWriteCard with the real pending_write once proposed', async () => {
    proposeAction.mockResolvedValue({ pending_write: { id: 'write-42' } })
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toHaveTextContent('write-42'))
    expect(screen.queryByRole('button', { name: 'Propose' })).not.toBeInTheDocument()
  })

  it("passes ActionForm's own onResolved through to PendingWriteCard unchanged", async () => {
    proposeAction.mockResolvedValue({ pending_write: { id: 'write-42' } })
    const { props } = renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))
    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'fake resolve' }))

    expect(props.onResolved).toHaveBeenCalledTimes(1)
  })
})

describe('ActionForm -- failure handling', () => {
  it("shows the backend's own generic error message on a non-401 failure", async () => {
    proposeAction.mockRejectedValue(new ApiError(403, 'Not authorized to perform this action'))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByText('Not authorized to perform this action')).toBeInTheDocument())
  })

  it('re-enables the buttons after a non-401 failure, stays on the form', async () => {
    proposeAction.mockRejectedValue(new ApiError(403, 'Not authorized to perform this action'))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Propose' })).not.toBeDisabled())
    expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument()
  })

  it('calls onSessionExpired and shows no error text on a 401', async () => {
    proposeAction.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderForm({ onSessionExpired })

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})

describe('ActionForm -- cancel', () => {
  it('clicking Cancel calls onCancel', () => {
    const { props } = renderForm()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(props.onCancel).toHaveBeenCalledTimes(1)
  })

  it('does not call proposeAction when Cancel is clicked', () => {
    renderForm()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(proposeAction).not.toHaveBeenCalled()
  })
})
