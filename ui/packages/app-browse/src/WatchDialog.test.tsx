/**
 * The Watch dialog: when to notify, who else, and what to propose.
 *
 * AND A REFUSAL IS SHOWN. The first Watch dropped every error that was
 * not an expired session -- harmless while nothing could be refused.
 * Now the server validates actions and recipients, so its words have
 * to reach the person.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    createTrigger: vi.fn(),
    getVisibleActionTypes: vi.fn(),
    getCurrentUser: vi.fn(),
    getDataFreshness: vi.fn(),
    getDeploymentConfig: vi.fn(),
    getSavedViews: vi.fn(),
    getMyVisibleSchema: vi.fn(),
  }
})

import {
  ApiError,
  createTrigger,
  getCurrentUser,
  getDataFreshness,
  getDeploymentConfig,
  getMyVisibleSchema,
  getSavedViews,
  getVisibleActionTypes,
} from '@elysium/shell-api/api'
import WatchDialog from './WatchDialog'

const mockedCreate = vi.mocked(createTrigger)

const VIEW = {
  view_id: 'v1',
  name: 'High value',
  object_type: 'Transaction',
  query_text: '',
  conditions: [],
  presentation: {},
  created_at: '2026-01-01T00:00:00+00:00',
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedCreate.mockResolvedValue('t1')
  vi.mocked(getVisibleActionTypes).mockResolvedValue({
    RecategorizeTransactions: {
      executable: true,
      automatable: true,
      parameters: {
        transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
        new_category: { type: 'string', display_name: 'New category' },
      },
    },
  })
  vi.mocked(getCurrentUser).mockResolvedValue({ role_name: 'analyst' })
  // THE PERSON'S OTHER VIEWS, for "and also when". Their own, as the
  // server lists them; the one being watched is left out by the dialog.
  vi.mocked(getSavedViews).mockResolvedValue([VIEW, { ...VIEW, view_id: 'v2', name: 'Open tickets' }])
  // Transaction data up to 26.4 hours behind: a nightly deployment.
  vi.mocked(getDataFreshness).mockResolvedValue({
    source: 'gold',
    last_synced_at: null,
    freshness: { Transaction: { state: 'fresh', warn_after_hours: 26.4, fail_after_hours: 50.4 } },
  } as unknown as Awaited<ReturnType<typeof getDataFreshness>>)
  // A REAL 403, as the server sends for anybody without manage:users.
  // A first version rejected with a plain Error, which the dialog now
  // correctly treats as a FAILURE -- so every test ran under a failure
  // nobody asserted on. A mock that is not the real refusal hides
  // exactly the distinction being tested.
  vi.mocked(getDeploymentConfig).mockRejectedValue(new ApiError(403, 'forbidden'))
  // NO DATE FIELD unless a test gives one, so the other tests see the
  // dialog as it was.
  vi.mocked(getMyVisibleSchema).mockResolvedValue({ Transaction: { fields: { amount: { data_type: 'number' } } } })
})

function open() {
  return render(<WatchDialog view={VIEW} onClose={vi.fn()} />)
}

describe('recipients', () => {
  it('offers only the person their own role', async () => {
    /** /config refused them, so they may name only what they hold. */
    open()

    expect(await screen.findByLabelText('analyst')).toBeInTheDocument()
  })

  it('sends a chosen role', async () => {
    open()
    fireEvent.click(await screen.findByLabelText('analyst'))
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ recipient_roles: ['analyst'] })),
    )
  })

  it('offers every role to somebody who can see them all', async () => {
    vi.mocked(getDeploymentConfig).mockResolvedValue({ role_names: ['analyst', 'reviewer'] })
    open()

    expect(await screen.findByLabelText('reviewer')).toBeInTheDocument()
  })
})

describe('an action', () => {
  it('is not proposed unless chosen', async () => {
    /** THE COMMON CASE is a trigger that only tells its owner. */
    open()
    await screen.findByLabelText('Action to propose')
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ action_type: null })))
  })

  it('sends the action, its target and its other values', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })
    fireEvent.change(await screen.findByLabelText('New category'), {
      target: { value: 'reviewed' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          action_type: 'RecategorizeTransactions',
          action_parameter: 'transaction_ids',
          action_values: { new_category: 'reviewed' },
        }),
      ),
    )
  })
})

describe('the parameter the matched objects are passed as', () => {
  /**
   * The effect that set this synchronously when the chosen action
   * changed was react/set-state-in-effect. What it was FOR had no
   * test: switching actions must not keep the previous action's
   * parameter, which would send objects as a parameter the new action
   * does not have.
   *
   * Two actions with DIFFERENT parameter names, which the single
   * fixture above could not express.
   */
  beforeEach(() => {
    vi.mocked(getVisibleActionTypes).mockResolvedValue({
      RecategorizeTransactions: {
        executable: true,
        automatable: true,
        parameters: {
          transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
          also_transactions: { type: 'object_reference_list', object_type: 'Transaction' },
        },
      },
      FlagTransactions: {
        executable: true,
        automatable: true,
        parameters: {
          flagged_ids: { type: 'object_reference_list', object_type: 'Transaction' },
          other_ids: { type: 'object_reference_list', object_type: 'Transaction' },
        },
      },
    })
  })

  it('defaults to the chosen action\u2019s own first parameter', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'FlagTransactions' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ action_parameter: 'flagged_ids' })),
    )
  })

  it('does not carry a parameter across to an action that lacks it', async () => {
    open()
    const action = await screen.findByLabelText('Action to propose')

    fireEvent.change(action, { target: { value: 'RecategorizeTransactions' } })
    fireEvent.change(screen.getByLabelText('Parameter for matched objects'), {
      target: { value: 'also_transactions' },
    })
    // Now switch: 'also_transactions' does not exist on FlagTransactions.
    fireEvent.change(action, { target: { value: 'FlagTransactions' } })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ action_parameter: 'flagged_ids' })),
    )
  })

  it('remembers a deliberate choice while the action stays the same', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })
    fireEvent.change(screen.getByLabelText('Parameter for matched objects'), {
      target: { value: 'also_transactions' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ action_parameter: 'also_transactions' })),
    )
  })
})

describe('when the server refuses', () => {
  it('shows its reason', async () => {
    mockedCreate.mockRejectedValue(new Error('You cannot notify the role analyst.'))
    open()
    await screen.findByLabelText('analyst')
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    expect(await screen.findByText(/cannot notify the role/)).toBeInTheDocument()
  })

  it('stays open, so the person can fix it', async () => {
    const onClose = vi.fn()
    mockedCreate.mockRejectedValue(new Error('refused'))
    render(<WatchDialog view={VIEW} onClose={onClose} />)
    await screen.findByLabelText('analyst')
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await screen.findByText('refused')
    expect(onClose).not.toHaveBeenCalled()
  })
})

describe('what could not be loaded', () => {
  it('is named, not hidden', async () => {
    /** A QUIET PARTIAL IS A WRONG ANSWER REPORTING SUCCESS. An empty
     *  "And propose" would say no action fits, when the truth is the
     *  actions could not be fetched. */
    vi.mocked(getVisibleActionTypes).mockRejectedValue(new Error('server unavailable'))
    open()

    expect(await screen.findByRole('alert')).toHaveTextContent(/Could not load actions/)
  })

  it('leaves the dialog usable', async () => {
    vi.mocked(getVisibleActionTypes).mockRejectedValue(new Error('server unavailable'))
    open()
    await screen.findByRole('alert')

    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() => expect(mockedCreate).toHaveBeenCalled())
  })

  it('does not report a 403 from the role list', async () => {
    /** THE RULE WORKING, not a failure: without manage:users a person
     *  names only their own role. */
    open()
    await screen.findByLabelText('analyst')

    expect(screen.queryByText(/Could not load/)).toBeNull()
  })

  it('does report any other failure of the role list', async () => {
    vi.mocked(getDeploymentConfig).mockRejectedValue(new ApiError(500, 'broken'))
    open()

    expect(await screen.findByRole('alert')).toHaveTextContent(/the list of roles/)
  })
})

describe('who approves what it proposes (decided 16 October)', () => {
  it('says, while choosing, when someone other than you must approve each proposal', async () => {
    vi.mocked(getVisibleActionTypes).mockResolvedValue({
      RecategorizeTransactions: {
        executable: true,
        automatable: true,
        automation_needs_another_approver: true,
        parameters: {
          transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
          new_category: { type: 'string', display_name: 'New category' },
        },
      },
    })
    open()
    const select = await screen.findByLabelText('Action to propose')
    expect(screen.getByText(/Somebody still decides/)).toBeInTheDocument()

    fireEvent.change(select, { target: { value: 'RecategorizeTransactions' } })

    expect(await screen.findByText(/Someone other than you must approve each one/)).toBeInTheDocument()
  })

  it('says nothing of the kind for an action without that rule', async () => {
    open()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })

    expect(screen.getByText(/Somebody still decides/)).toBeInTheDocument()
    expect(screen.queryByText(/Someone other than you/)).not.toBeInTheDocument()
  })
})

describe('a window shorter than the data is current (16 October)', () => {
  it('says so before the watch is made', async () => {
    const recent = {
      ...VIEW,
      conditions: [{ field: 'transaction_date', operator: 'relative_date', value: { since_hours_ago: 4 } }],
    }
    render(<WatchDialog view={recent} onClose={() => {}} onSessionExpired={() => {}} />)

    expect(await screen.findByRole('note')).toHaveTextContent('up to 26 hours behind its source')
  })

  it('says nothing for a view without a short date window', async () => {
    render(<WatchDialog view={VIEW} onClose={() => {}} onSessionExpired={() => {}} />)
    await waitFor(() => expect(vi.mocked(getDataFreshness)).toHaveBeenCalled())

    expect(screen.queryByRole('note')).toBeNull()
  })
})

describe('combined, held and scheduled (17 October)', () => {
  async function openIt() {
    render(<WatchDialog view={VIEW} onClose={() => {}} onSessionExpired={() => {}} />)
    await waitFor(() => expect(vi.mocked(getSavedViews)).toHaveBeenCalled())
  }

  function submit() {
    fireEvent.click(screen.getByRole('button', { name: /^Watch$/ }))
  }

  it('sends at most as a state', async () => {
    await openIt()
    fireEvent.change(screen.getByLabelText('When to notify'), { target: { value: 'at_most' } })
    submit()

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ at_most: 10, above: null })),
    )
  })

  it('adds a condition on another of their views, joined by or', async () => {
    await openIt()
    fireEvent.click(await screen.findByRole('button', { name: /And also when another view is/ }))
    fireEvent.change(screen.getByLabelText('Combine'), { target: { value: 'any' } })
    fireEvent.change(screen.getByLabelText('Condition 2 count'), { target: { value: '50' } })
    submit()

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({ also: [{ view_id: 'v2', above: 50 }], combine: 'any' }),
      ),
    )
  })

  it('holds for hours, sent in minutes', async () => {
    await openIt()
    fireEvent.click(screen.getByLabelText('only once it has been true for at least'))
    fireEvent.change(screen.getByLabelText('Hold for'), { target: { value: '2' } })
    submit()

    await waitFor(() => expect(mockedCreate).toHaveBeenCalledWith(expect.objectContaining({ hold_minutes: 120 })))
  })

  it('checks on a schedule in the browser zone, and offers no hold beside it', async () => {
    await openIt()
    fireEvent.click(screen.getByLabelText('only check on'))

    expect(screen.queryByLabelText('only once it has been true for at least')).toBeNull()
    fireEvent.change(screen.getByLabelText('Check at'), { target: { value: '08:15' } })
    submit()

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          schedule: { days: [0, 1, 2, 3, 4], time: '08:15' },
          timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
        }),
      ),
    )
  })

  it('offers none of it for gaining or losing, which are changes, not states', async () => {
    await openIt()
    fireEvent.change(screen.getByLabelText('When to notify'), { target: { value: 'gained' } })

    expect(screen.queryByLabelText('only check on')).toBeNull()
    expect(screen.queryByRole('button', { name: /And also when/ })).toBeNull()
  })

  it('a held watch keeps its action', async () => {
    await openIt()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })
    fireEvent.click(screen.getByLabelText('only once it has been true for at least'))
    submit()

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({ action_type: 'RecategorizeTransactions', hold_minutes: 60 }),
      ),
    )
  })

  it("takes the action's objects from the condition chosen, and says which", async () => {
    await openIt()
    fireEvent.click(await screen.findByRole('button', { name: /And also when another view is/ }))
    fireEvent.change(screen.getByLabelText('Objects for the action'), { target: { value: 'v2' } })
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })
    submit()

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({ action_type: 'RecategorizeTransactions', action_view_id: 'v2' }),
      ),
    )
  })

  it("offers only actions that take the chosen view's objects", async () => {
    vi.mocked(getSavedViews).mockResolvedValue([
      VIEW,
      { ...VIEW, view_id: 'v3', name: 'Customers', object_type: 'Customer' },
    ])
    await openIt()
    fireEvent.click(await screen.findByRole('button', { name: /And also when another view is/ }))
    fireEvent.change(screen.getByLabelText('Objects for the action'), { target: { value: 'v3' } })

    expect(screen.queryByLabelText('Action to propose')).toBeNull()
  })
})

describe('projected above (R68)', () => {
  it('an action chosen first is not sent once projected is chosen', async () => {
    vi.mocked(getMyVisibleSchema).mockResolvedValue({
      Transaction: { fields: { booked: { data_type: 'date', display_name: 'Booked' } } },
    })
    open()
    fireEvent.change(await screen.findByLabelText('Action to propose'), {
      target: { value: 'RecategorizeTransactions' },
    })
    await screen.findByRole('option', { name: 'projected above' })
    fireEvent.change(screen.getByLabelText('When to notify'), { target: { value: 'projected' } })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({ projected_field: 'booked', action_type: null, action_values: {} }),
      ),
    )
  })

  function withDates() {
    vi.mocked(getMyVisibleSchema).mockResolvedValue({
      Transaction: {
        fields: {
          amount: { data_type: 'number' },
          booked: { data_type: 'date', display_name: 'Booked' },
          hidden_date: { data_type: 'date', readable: false },
        },
      },
    })
  }

  it('is offered only for a view whose type has a date field it may read', async () => {
    open()
    await screen.findByLabelText('analyst')
    expect(screen.queryByRole('option', { name: 'projected above' })).not.toBeInTheDocument()
  })

  it('sends the date field, the period and the line, and nothing beside them', async () => {
    withDates()
    open()
    const when = await screen.findByLabelText('When to notify')
    await screen.findByRole('option', { name: 'projected above' })
    fireEvent.change(when, { target: { value: 'projected' } })
    expect(screen.getByLabelText('Date field')).toHaveValue('booked')
    // A DATE THEY MAY NOT READ is not offered: its totals would be none.
    expect(screen.queryByRole('option', { name: 'hidden_date' })).not.toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Per'), { target: { value: 'month' } })
    expect(screen.getByText(/counted per month, forecast/)).toBeInTheDocument()
    // NO ACTION BESIDE IT: the server refuses one.
    expect(screen.queryByText('And propose')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          projected_field: 'booked',
          projected_period: 'month',
          projected_above: 10,
          above: null,
          gained: null,
          fell: null,
          at_most: null,
          action_type: null,
        }),
      ),
    )
  })
})
