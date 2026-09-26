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
    getDeploymentConfig: vi.fn(),
  }
})

import {
  ApiError,
  createTrigger,
  getCurrentUser,
  getDeploymentConfig,
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
  // A REAL 403, as the server sends for anybody without manage:users.
  // A first version rejected with a plain Error, which the dialog now
  // correctly treats as a FAILURE -- so every test ran under a failure
  // nobody asserted on. A mock that is not the real refusal hides
  // exactly the distinction being tested.
  vi.mocked(getDeploymentConfig).mockRejectedValue(new ApiError(403, 'forbidden'))
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
