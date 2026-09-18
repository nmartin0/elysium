/**
 * One action, applied to the objects a person chose.
 *
 * SEPARATE FROM ActionForm RATHER THAN A MODE OF IT. ActionForm fills
 * an object_reference from the page it was opened on, and every
 * parameter is typed by hand. Here the object_reference_list comes
 * from the SELECTION and cannot be typed -- there is no sensible
 * control for "paste a thousand ids". Folding them together would mean
 * a form that behaves differently depending on a parameter type nobody
 * can see.
 */

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import BulkActionForm from './BulkActionForm'

vi.mock('@elysium/shell-api/api', () => ({
  proposeAction: vi.fn(),
  getErrorMessage: (error: unknown) => String((error as Error)?.message ?? error),
}))

const { proposeAction } = await import('@elysium/shell-api/api')
const mockedPropose = vi.mocked(proposeAction)

const ACTION = {
  name: 'RecategorizeTransactions',
  parameters: {
    transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
    new_category: { type: 'string', required: true, display_name: 'New category' },
  },
}

beforeEach(() => {
  mockedPropose.mockReset()
  mockedPropose.mockResolvedValue({})
})

describe('BulkActionForm', () => {
  it('sends the selected ids as the list parameter', async () => {
    render(<BulkActionForm action={ACTION} objectType="Transaction" objectIds={['1', '2', '3']} onDone={vi.fn()} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'audited' } })
    fireEvent.click(screen.getByText('Propose'))

    await waitFor(() =>
      expect(mockedPropose).toHaveBeenCalledWith('RecategorizeTransactions', {
        new_category: 'audited',
        transaction_ids: ['1', '2', '3'],
      }),
    )
  })

  it('offers no input for the list parameter', () => {
    // It is filled from the selection, so an input would invite
    // someone to contradict what they just chose.
    render(<BulkActionForm action={ACTION} objectType="Transaction" objectIds={['1']} onDone={vi.fn()} />)

    expect(screen.getAllByRole('textbox')).toHaveLength(1)
    expect(screen.queryByText(/transaction_ids/i)).toBeNull()
  })

  it('says how many objects it will touch', () => {
    // Restated even though the selection bar showed it: this is the
    // last screen before a write that touches every one of them.
    render(<BulkActionForm action={ACTION} objectType="Transaction" objectIds={['1', '2', '3']} onDone={vi.fn()} />)

    expect(screen.getByText(/3 Transaction objects/)).toBeInTheDocument()
  })

  it("shows the server's own refusal", async () => {
    // Including the ceiling. The UI warns at 1000 as a courtesy; the
    // server enforces it, and its message names the count and the
    // remedy.
    mockedPropose.mockRejectedValue(new Error('names 1200 objects, and at most 1000 may be'))
    render(<BulkActionForm action={ACTION} objectType="Transaction" objectIds={['1']} onDone={vi.fn()} />)

    fireEvent.click(screen.getByText('Propose'))

    expect(await screen.findByRole('alert')).toHaveTextContent(/at most 1000/)
  })

  it('does not call onDone when the proposal failed', async () => {
    // THE CONTROL. Closing the form on failure would look like
    // success and lose what was typed.
    const onDone = vi.fn()
    mockedPropose.mockRejectedValue(new Error('refused'))
    render(<BulkActionForm action={ACTION} objectType="Transaction" objectIds={['1']} onDone={onDone} />)

    fireEvent.click(screen.getByText('Propose'))

    await screen.findByRole('alert')
    expect(onDone).not.toHaveBeenCalled()
  })

  it('refuses an action with no list parameter for this type', () => {
    // Not reachable through the menu, which filters them out. Stated
    // rather than assumed, because an action rendered here without one
    // would silently write to nothing.
    const single = {
      name: 'RecategorizeTransaction',
      parameters: { transaction_id: { type: 'object_reference', object_type: 'Transaction' } },
    }
    render(<BulkActionForm action={single} objectType="Transaction" objectIds={['1']} onDone={vi.fn()} />)

    expect(screen.getByRole('alert')).toHaveTextContent(/cannot be applied to a selection/)
  })
})
