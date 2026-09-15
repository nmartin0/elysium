/**
 * Which actions can be applied to a selection.
 *
 * THE ONTOLOGY DECIDES, not the UI. Foundry: "in 'bulk' contexts...
 * only actions that accept object list parameters of the correct type
 * will be shown". An action without an object_reference_list parameter
 * for THIS object type is not a bulk action, and offering it would be
 * an invitation to a refusal -- the write mediator would reject it
 * after a whole form was filled in.
 */

import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import BulkActionsMenu from './BulkActionsMenu'

const BULK = {
  name: 'RecategorizeTransactions',
  parameters: {
    transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
    new_category: { type: 'string' },
  },
}

const SINGLE = {
  name: 'RecategorizeTransaction',
  parameters: {
    transaction_id: { type: 'object_reference', object_type: 'Transaction' },
  },
}

const WRONG_TYPE = {
  name: 'MergeCustomers',
  parameters: {
    customer_ids: { type: 'object_reference_list', object_type: 'Customer' },
  },
}

describe('BulkActionsMenu', () => {
  it('offers an action that takes a list of this type', () => {
    render(<BulkActionsMenu actions={[BULK]} objectType="Transaction" count={3} onChoose={vi.fn()} />)

    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('RecategorizeTransactions')).toBeInTheDocument()
  })

  it('does NOT offer a single-object action', () => {
    // It would be accepted by the menu and refused by the write
    // mediator, which expects one object_reference and would receive a
    // list.
    render(<BulkActionsMenu actions={[SINGLE]} objectType="Transaction" count={3} onChoose={vi.fn()} />)

    expect(screen.queryByRole('button')).toBeNull()
  })

  it('does NOT offer a list action for the wrong object type', () => {
    /** "OF THE CORRECT TYPE" matters as much as the list-ness.
     *
     * An action taking a list of Customers must not appear on a list
     * of Transactions: the ids would be accepted by the form and
     * rejected at the far end, after someone filled in a whole form.
     */
    render(<BulkActionsMenu actions={[WRONG_TYPE]} objectType="Transaction" count={3} onChoose={vi.fn()} />)

    expect(screen.queryByRole('button')).toBeNull()
  })

  it('shows only the applicable ones when both kinds exist', () => {
    // THE CONTROL. A menu that showed everything would pass the first
    // test while being wrong.
    render(
      <BulkActionsMenu actions={[BULK, SINGLE, WRONG_TYPE]} objectType="Transaction" count={3} onChoose={vi.fn()} />,
    )

    fireEvent.click(screen.getByRole('button'))

    expect(screen.getByText('RecategorizeTransactions')).toBeInTheDocument()
    expect(screen.queryByText('RecategorizeTransaction')).toBeNull()
    expect(screen.queryByText('MergeCustomers')).toBeNull()
  })

  it('is absent rather than disabled when nothing qualifies', () => {
    // A disabled menu invites someone to work out what would enable
    // it, and the answer is "the ontology would have to declare a
    // different action" -- not something they can do from this screen.
    const { container } = render(<BulkActionsMenu actions={[]} objectType="Transaction" count={3} onChoose={vi.fn()} />)

    expect(container.firstChild).toBeNull()
  })

  it('says how many objects would be acted on', () => {
    // Restated where the decision is made. "Apply to 3" and "apply to
    // 900" are the same click.
    render(<BulkActionsMenu actions={[BULK]} objectType="Transaction" count={900} onChoose={vi.fn()} />)

    expect(screen.getByRole('button')).toHaveTextContent('900')
  })

  it('reports which action was chosen', () => {
    const onChoose = vi.fn()
    render(<BulkActionsMenu actions={[BULK]} objectType="Transaction" count={3} onChoose={onChoose} />)

    fireEvent.click(screen.getByRole('button'))
    fireEvent.click(screen.getByText('RecategorizeTransactions'))

    expect(onChoose).toHaveBeenCalledWith(BULK)
  })
})
