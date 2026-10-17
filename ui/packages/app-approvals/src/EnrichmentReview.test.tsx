import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getEnrichmentRecipes: vi.fn(),
  decideEnrichmentRecipe: vi.fn(),
}))

import { decideEnrichmentRecipe, type EnrichmentRecipe, getEnrichmentRecipes } from '@elysium/shell-api/api'
import EnrichmentReview, { heldOutSentence } from './EnrichmentReview'

const mockedList = vi.mocked(getEnrichmentRecipes)
const mockedDecide = vi.mocked(decideEnrichmentRecipe)

function recipe(overrides: Partial<EnrichmentRecipe> = {}): EnrichmentRecipe {
  return {
    recipe_id: 'r1',
    object_type: 'SupportTicket',
    field_name: 'topic',
    field_label: 'Topic',
    instruction: 'What the ticket is about.',
    choices: ['billing', 'refund'],
    inputs: ['subject'],
    status: 'proposed',
    rules: ["If subject mentions 'refund': refund"],
    evaluation: {
      enough_to_judge: true,
      held_out: { rows: 10, covered: 8, agreed: 7, coverage: 0.8, agreement: 0.875 },
    },
    provenance: { model: 'phi4-mini', sample: 20, compartment: 'us-west' },
    current: true,
    proposed_at: '2026-10-15T09:00:00+00:00',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('reviewing enrichment rules (R41)', () => {
  it('shows the question, the rules in words, and the score on rows they were not written from', async () => {
    mockedList.mockResolvedValue([recipe()])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'SupportTicket Topic' })
    expect(within(card).getByText('What the ticket is about.')).toBeInTheDocument()
    expect(within(card).getByText("If subject mentions 'refund': refund")).toBeInTheDocument()
    expect(within(card).getByText(/not written from, they gave an answer for 80%.*on 88% of those/)).toBeInTheDocument()
    expect(within(card).getByText(/sample of 20 in us-west/)).toBeInTheDocument()
  })

  it('a vote shows every rule set with its weight, and says how they combine', async () => {
    mockedList.mockResolvedValue([
      recipe({
        rule_sets: [
          { weight: 2.2, rules: ["If subject mentions 'refund': refund"] },
          { weight: 1.1, rules: ["If subject mentions 'invoice': billing"] },
        ],
      }),
    ])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'SupportTicket Topic' })
    expect(within(card).getByRole('heading', { name: '2 rule sets that vote' })).toBeInTheDocument()
    expect(within(card).getByText(/a tie is left empty/)).toBeInTheDocument()
    const second = within(card).getByRole('heading', { name: 'Set 2, weight 1.1' }).closest('section')!
    expect(within(second).getByText("If subject mentions 'invoice': billing")).toBeInTheDocument()
    expect(within(card).queryByText('The rules, first match wins')).not.toBeInTheDocument()
  })

  it('one rule set reads as before, with no weight', async () => {
    mockedList.mockResolvedValue([
      recipe({ rule_sets: [{ weight: null, rules: ["If subject mentions 'refund': refund"] }] }),
    ])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'SupportTicket Topic' })
    expect(within(card).getByText('The rules, first match wins')).toBeInTheDocument()
    expect(within(card).queryByText(/weight/)).not.toBeInTheDocument()
  })

  it('approving records the decision and says nothing changes until the sync', async () => {
    mockedList.mockResolvedValue([recipe()])
    mockedDecide.mockResolvedValue(
      recipe({ status: 'approved', decided_by: 'ops', decided_at: '2026-10-15T10:00:00+00:00' }),
    )
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Approving fills Topic at the next sync/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(mockedDecide).toHaveBeenCalledWith('r1', true))
    expect(await screen.findByText('approved')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('offers no buttons for rules written for a question that has since changed, and says why', async () => {
    mockedList.mockResolvedValue([recipe({ current: false })])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/question has changed since these rules were written/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('warns when the held-out rows are too few to judge by', async () => {
    mockedList.mockResolvedValue([recipe({ evaluation: { enough_to_judge: false } })])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)
    expect(await screen.findByText(/Too few rows to judge by/)).toBeInTheDocument()
  })

  it('says why the list is empty, rather than showing nothing', async () => {
    mockedList.mockResolvedValue([])
    render(<EnrichmentReview onSessionExpired={vi.fn()} />)
    expect(await screen.findByText(/only for fields you may read, in your own compartment/)).toBeInTheDocument()
  })

  it('the held-out sentence admits when there was nothing to judge on', () => {
    expect(heldOutSentence(recipe({ evaluation: {} }))).toBe('There were no held-out rows to judge these rules on.')
  })
})
