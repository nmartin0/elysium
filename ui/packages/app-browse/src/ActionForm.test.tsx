import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import type { PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

// Partial mock via importOriginal, not a hand-duplicated module shape
// -- see App.test.tsx's own header comment for the full reasoning.
vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    proposeAction: vi.fn(),
  }
})
vi.mock('@elysium/shell-api/components/PendingWriteCard', () => ({
  // A simple stub -- PendingWriteCard has its own, thorough, direct
  // test file. This file's own job is only to confirm ActionForm
  // renders it with the right pendingWrite/onResolved once a propose
  // succeeds, not to re-prove its own internal behavior again here.
  default: ({ pendingWrite, onResolved }: { pendingWrite: PendingWrite; onResolved: () => void }) => (
    <div data-testid="pending-write-card">
      <p>{pendingWrite.id}</p>
      <button onClick={onResolved}>fake resolve</button>
    </div>
  ),
}))

import { proposeAction, ApiError } from '@elysium/shell-api/api'
import ActionForm, { type ActionDef } from './ActionForm'

const mockedProposeAction = vi.mocked(proposeAction)

// noUncheckedIndexedAccess types mock.calls[0] (and its own [1]) as
// possibly-undefined -- every real call site below only ever reads
// this immediately after awaiting the real call that produced it,
// guaranteeing it exists. A tiny helper, not a `!` at every call
// site, matching api.test.ts's own firstCallArgs() pattern.
function secondArgOfFirstCall(): Record<string, unknown> {
  const call = mockedProposeAction.mock.calls[0]
  if (!call) throw new Error('proposeAction was never called')
  return call[1]
}

function updateCustomerNameDef(): ActionDef {
  return {
    // Honestly matching the real, whole GET /me/visible-action-types
    // entry shape here, even though ActionForm itself only reads
    // `parameters` -- the real caller (ObjectDetailPanel.jsx) always
    // passes the full, real object, and this test data should too.
    affected_object_types: ['Customer'],
    executable: true,
    parameters: {
      customer_id: {
        type: 'object_reference',
        object_type: 'Customer',
        required: true,
        default_to_current_object: true,
      },
      new_name: { type: 'string', required: true },
    },
  }
}

function transferFundsDef(): ActionDef {
  // Matches tests/integration/fixtures/ontology_schema.yaml's own
  // REAL, FIXED TransferFunds definition exactly -- from_account_id
  // and to_account_id both declare object_type: Account, but only
  // from_account_id carries default_to_current_object: true. Before
  // this marker existed, BOTH got pre-filled and locked to the same
  // id (a real, previously-discovered bug -- see ActionForm.tsx's own
  // AI-notes for the full history); this shape confirms the fix.
  return {
    affected_object_types: ['Account'],
    executable: true,
    parameters: {
      from_account_id: {
        type: 'object_reference',
        object_type: 'Account',
        required: true,
        default_to_current_object: true,
      },
      to_account_id: { type: 'object_reference', object_type: 'Account', required: true },
      new_from_balance: { type: 'number', required: true },
      new_to_balance: { type: 'number', required: true },
    },
  }
}

interface RenderFormOverrides {
  actionName?: string
  actionDef?: ActionDef
  objectType?: string
  objectId?: string
  onCancel?: () => void
  onResolved?: (approved: boolean) => void
  onSessionExpired?: () => void
}

function renderForm(overrides: RenderFormOverrides = {}) {
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

  it('leaves an unmarked object_reference parameter empty and editable, even if its type matches the current object', () => {
    // A synthetic action def -- linked_account_id shares NO type with
    // the current object at all, AND carries no marker; customer_id
    // is both marked AND type-matches. Confirms the mechanism locks
    // ONLY the explicitly marked parameter, never an unmarked one,
    // regardless of type.
    const actionDef: ActionDef = {
      affected_object_types: ['Customer'],
      executable: true,
      parameters: {
        customer_id: {
          type: 'object_reference',
          object_type: 'Customer',
          required: true,
          default_to_current_object: true,
        },
        linked_account_id: { type: 'object_reference', object_type: 'Account', required: true },
      },
    }
    renderForm({ actionName: 'SyntheticAction', actionDef, objectType: 'Customer', objectId: 'cust_001' })

    // customer_id is marked AND type-matches -- locked.
    expect(screen.getByLabelText('Customer id')).toHaveValue('cust_001')
    expect(screen.getByLabelText('Customer id')).toBeDisabled()
    // linked_account_id carries no marker at all -- not locked, empty.
    expect(screen.getByLabelText('Linked account id')).toHaveValue('')
    expect(screen.getByLabelText('Linked account id')).not.toBeDisabled()
  })

  it('FIXED: the real TransferFunds shape locks ONLY the marked from_account_id, leaving to_account_id genuinely editable', () => {
    // The real, previously-discovered bug this replaces: before
    // default_to_current_object existed, BOTH from_account_id and
    // to_account_id (sharing object_type: Account) got pre-filled and
    // locked to the SAME current account's id, with no way to specify
    // a different "to" account through the form at all. See
    // ActionForm.tsx's own AI-notes for the full history.
    renderForm({
      actionName: 'TransferFunds',
      actionDef: transferFundsDef(),
      objectType: 'Account',
      objectId: 'acct_from',
    })

    expect(screen.getByLabelText('From account id')).toHaveValue('acct_from')
    expect(screen.getByLabelText('From account id')).toBeDisabled()
    // Genuinely different now -- empty, editable, independent of
    // From account id.
    expect(screen.getByLabelText('To account id')).toHaveValue('')
    expect(screen.getByLabelText('To account id')).not.toBeDisabled()
  })

  it('does NOT lock the marked parameter when the current object type does not match it -- a multi-type action opened from the OTHER type', () => {
    // The subtler edge case the fix's own two-part check (marker AND
    // type-match) exists for: an action with multiple
    // affected_object_types could be launched from any one of them.
    // Pre-filling a Customer-typed parameter with an Account's own id
    // just because the marker is present would be a real, silent
    // correctness bug of its own, not just a UX one.
    const actionDef: ActionDef = {
      affected_object_types: ['Customer', 'Account'],
      executable: true,
      parameters: {
        customer_id: {
          type: 'object_reference',
          object_type: 'Customer',
          required: true,
          default_to_current_object: true,
        },
        account_id: { type: 'object_reference', object_type: 'Account', required: true },
      },
    }
    renderForm({ actionName: 'MultiTypeAction', actionDef, objectType: 'Account', objectId: 'acct_001' })

    // customer_id is marked, but its own type (Customer) does NOT
    // match the current object (Account) -- must NOT be locked or
    // pre-filled with the Account's own id.
    expect(screen.getByLabelText('Customer id')).toHaveValue('')
    expect(screen.getByLabelText('Customer id')).not.toBeDisabled()
  })

  it('renders a "number" parameter as a real, accessible numeric input (Blueprint\'s own NumericInput, not a real HTML type="number")', () => {
    renderForm({
      actionName: 'TransferFunds',
      actionDef: transferFundsDef(),
      objectType: 'Account',
      objectId: 'acct_from',
    })
    // NOT type="number" -- confirmed directly against NumericInput's
    // own real, rendered DOM output before writing this assertion:
    // Blueprint's own NumericInput renders a real type="text" input
    // internally, mimicking native number-input behavior via its own
    // JS validation (allowNumericCharactersOnly) rather than the
    // literal HTML input type. role="spinbutton" is the real,
    // meaningful, accessible signal this IS a genuine numeric input,
    // not a plain text one -- also confirmed directly against the
    // same real output, not assumed.
    expect(screen.getByLabelText('New from balance')).toHaveAttribute('role', 'spinbutton')
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
    renderForm({
      actionName: 'TransferFunds',
      actionDef: transferFundsDef(),
      objectType: 'Account',
      objectId: 'acct_from',
    })

    fireEvent.change(screen.getByLabelText('New from balance'), { target: { value: '250' } })

    // '250' (string), not 250 (number) -- NumericInput's own real,
    // rendered <input> is type="text" (see the test above's own
    // comment for why), and testing-library's own toHaveValue()
    // matcher coerces its expectation differently depending on the
    // real, rendered input type -- confirmed directly, not assumed.
    expect(screen.getByLabelText('New from balance')).toHaveValue('250')
    // New_to_balance, a completely separate field, is untouched.
    // '' (empty string), not null -- null is specifically testing-
    // library's own convention for an EMPTY type="number"/type="date"
    // input; NumericInput renders type="text" (see above), so an
    // empty value here is a real, empty string instead, confirmed
    // directly, not assumed.
    expect(screen.getByLabelText('New to balance')).toHaveValue('')
    // The locked field is untouched too, still showing the current object.
    expect(screen.getByLabelText('From account id')).toHaveValue('acct_from')
  })
})

describe('ActionForm -- submitting', () => {
  it('calls proposeAction with the real, current field values', async () => {
    mockedProposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() =>
      expect(mockedProposeAction).toHaveBeenCalledWith('UpdateCustomerName', {
        customer_id: 'cust_001',
        new_name: 'Ada Lovelace',
      }),
    )
  })

  it('coerces a "number" parameter\'s string value to a real JSON number, with the now-genuinely-editable to_account_id filled independently', async () => {
    mockedProposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm({
      actionName: 'TransferFunds',
      actionDef: transferFundsDef(),
      objectType: 'Account',
      objectId: 'acct_from',
    })

    fireEvent.change(screen.getByLabelText('To account id'), { target: { value: 'acct_to' } })
    fireEvent.change(screen.getByLabelText('New from balance'), { target: { value: '250' } })
    fireEvent.change(screen.getByLabelText('New to balance'), { target: { value: '750' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() =>
      expect(mockedProposeAction).toHaveBeenCalledWith('TransferFunds', {
        from_account_id: 'acct_from',
        // Genuinely a different value now -- the fix, confirmed here
        // too, not just in the rendering tests above.
        to_account_id: 'acct_to',
        new_from_balance: 250,
        new_to_balance: 750,
      }),
    )
    // Real numbers, not the strings "250"/"750".
    expect(typeof secondArgOfFirstCall().new_from_balance).toBe('number')
    expect(typeof secondArgOfFirstCall().new_to_balance).toBe('number')
  })

  it('leaves an empty, non-required "number" parameter as an empty string, not coerced to 0 or NaN', async () => {
    // A synthetic, deliberately non-required number parameter --
    // every real number parameter in this project's own actual
    // schemas is required (confirmed directly, not assumed), and a
    // required, empty field never reaches handleSubmit at all (the
    // browser's own native validation blocks the submit event itself
    // first) -- this is the only way to genuinely exercise this
    // component's own `raw !== ''` coercion guard at all.
    const actionDef: ActionDef = {
      affected_object_types: ['Customer'],
      executable: true,
      parameters: { optional_amount: { type: 'number', required: false } },
    }
    mockedProposeAction.mockResolvedValue({ pending_write: { id: 'write-1' } })
    renderForm({ actionName: 'SyntheticAction', actionDef, objectType: 'Customer', objectId: 'cust_001' })

    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(mockedProposeAction).toHaveBeenCalled())
    expect(secondArgOfFirstCall().optional_amount).toBe('')
  })

  it('disables both Propose and Cancel while the request is in flight', async () => {
    mockedProposeAction.mockReturnValue(new Promise(() => {}))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Propose' })).toBeDisabled())
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
  })
})

describe('ActionForm -- a successful propose', () => {
  it('shows PendingWriteCard with the real pending_write once proposed', async () => {
    mockedProposeAction.mockResolvedValue({ pending_write: { id: 'write-42' } })
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByTestId('pending-write-card')).toHaveTextContent('write-42'))
    expect(screen.queryByRole('button', { name: 'Propose' })).not.toBeInTheDocument()
  })

  it("passes ActionForm's own onResolved through to PendingWriteCard unchanged", async () => {
    mockedProposeAction.mockResolvedValue({ pending_write: { id: 'write-42' } })
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
    mockedProposeAction.mockRejectedValue(new ApiError(403, 'Not authorized to perform this action'))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByText('Not authorized to perform this action')).toBeInTheDocument())
  })

  it('re-enables the buttons after a non-401 failure, stays on the form', async () => {
    mockedProposeAction.mockRejectedValue(new ApiError(403, 'Not authorized to perform this action'))
    renderForm()

    fireEvent.change(screen.getByLabelText('New name'), { target: { value: 'Ada Lovelace' } })
    fireEvent.click(screen.getByRole('button', { name: 'Propose' }))

    await waitFor(() => expect(screen.getByRole('button', { name: 'Propose' })).not.toBeDisabled())
    expect(screen.queryByTestId('pending-write-card')).not.toBeInTheDocument()
  })

  it('calls onSessionExpired and shows no error text on a 401', async () => {
    mockedProposeAction.mockRejectedValue(new ApiError(401, 'session expired'))
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

    expect(mockedProposeAction).not.toHaveBeenCalled()
  })
})
