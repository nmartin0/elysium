import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getUnusualReview: vi.fn(),
  decideUnusual: vi.fn(),
}))

import { decideUnusual, getUnusualReview, type UnusualReviewItem } from '@elysium/shell-api/api'
import UnusualReview from './UnusualReview'

const mockedList = vi.mocked(getUnusualReview)
const mockedDecide = vi.mocked(decideUnusual)

const REASON =
  'amount 300 is far above the usual 50.45 for the 667 records with category subscription; nine in ten of them are between 42.12 and 58.1.'

function item(overrides: Partial<UnusualReviewItem> = {}): UnusualReviewItem {
  return {
    object_type: 'Transaction',
    record_id: '2008',
    field: 'amount',
    field_label: 'Amount',
    value: 300,
    reason: REASON,
    compartment: 'us-west',
    decision: null,
    decided_by: null,
    ...overrides,
  }
}

function show() {
  return render(
    <MemoryRouter>
      <UnusualReview onSessionExpired={vi.fn()} />
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('values unusual for their kind, for a person to decide about (R51)', () => {
  it('the reason, the record it is on, and the two decisions', async () => {
    mockedList.mockResolvedValue({ items: [item()], found: 1 })
    show()

    const card = await screen.findByRole('article', { name: 'Transaction 2008 Amount' })
    expect(within(card).getByText(REASON)).toBeInTheDocument()
    expect(within(card).getByRole('link', { name: 'Transaction 2008' }).getAttribute('href')).toBe(
      '/objects/Transaction/2008',
    )
    expect(within(card).getByRole('button', { name: 'Expected' })).toBeInTheDocument()
    expect(within(card).getByRole('button', { name: 'Worth a look' })).toBeInTheDocument()
  })

  it('deciding sends which value, and moves it to Decided', async () => {
    mockedList.mockResolvedValue({ items: [item()], found: 1 })
    mockedDecide.mockResolvedValue(item({ decision: 'expected', decided_by: 'rev' }))
    show()

    fireEvent.click(await screen.findByRole('button', { name: 'Expected' }))

    await screen.findByText('Nothing is waiting for a decision.')
    expect(mockedDecide).toHaveBeenCalledWith(
      expect.objectContaining({ record_id: '2008', field: 'amount' }),
      'expected',
    )
    const decided = screen.getByRole('heading', { name: 'Decided' }).closest('section') as HTMLElement
    expect(within(decided).getByText('Marked expected by rev.')).toBeInTheDocument()
    // A DECISION CAN BE CHANGED, not repeated.
    expect(within(decided).queryByRole('button', { name: 'Expected' })).toBeNull()
    expect(within(decided).getByRole('button', { name: 'Worth a look' })).toBeInTheDocument()
  })

  it('worth a look is sent as itself, and the card says it was kept', async () => {
    mockedList.mockResolvedValue({ items: [item()], found: 1 })
    mockedDecide.mockResolvedValue(item({ decision: 'worth_a_look', decided_by: 'rev' }))
    show()

    fireEvent.click(await screen.findByRole('button', { name: 'Worth a look' }))

    expect(await screen.findByText('Marked worth a look by rev.')).toBeInTheDocument()
    expect(mockedDecide).toHaveBeenCalledWith(expect.objectContaining({ record_id: '2008' }), 'worth_a_look')
  })

  it('says how many there were when only the furthest are shown', async () => {
    mockedList.mockResolvedValue({ items: [item()], found: 212 })
    show()

    expect(await screen.findByText("The 1 furthest from their kind's usual, of 212 found.")).toBeInTheDocument()
  })

  it('says nothing of the sort when the list is whole', async () => {
    // THE CONTROL for the one above.
    mockedList.mockResolvedValue({ items: [item()], found: 1 })
    show()

    await screen.findByText(REASON)
    expect(screen.queryByText(/furthest from their kind/)).toBeNull()
  })

  it('a refusal is said on the card, and nothing moves', async () => {
    mockedList.mockResolvedValue({ items: [item()], found: 1 })
    mockedDecide.mockRejectedValue(new Error('No such unusual value'))
    show()

    fireEvent.click(await screen.findByRole('button', { name: 'Worth a look' }))

    await waitFor(() => expect(screen.getByText('No such unusual value')).toBeInTheDocument())
    expect(screen.queryByRole('heading', { name: 'Decided' })).toBeNull()
  })

  it('an empty queue says what would put something in it', async () => {
    mockedList.mockResolvedValue({ items: [], found: 0 })
    show()

    expect(await screen.findByText('Nothing unusual to review')).toBeInTheDocument()
  })
})
