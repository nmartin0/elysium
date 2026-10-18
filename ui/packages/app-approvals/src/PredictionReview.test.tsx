import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getPredictionProposals: vi.fn(),
  decidePredictionProposal: vi.fn(),
}))

import { decidePredictionProposal, getPredictionProposals, type PredictionProposal } from '@elysium/shell-api/api'
import PredictionReview, { holdsSentence, scoreSentence } from './PredictionReview'

const mockedList = vi.mocked(getPredictionProposals)
const mockedDecide = vi.mocked(decidePredictionProposal)

function proposal(overrides: Partial<PredictionProposal> = {}): PredictionProposal {
  return {
    proposal_id: 'p1',
    object_type: 'Customer',
    field_name: 'churn_risk',
    field_label: 'Churn risk',
    target: 'churned',
    target_label: 'Churned',
    kind: 'chance',
    chance_of: 'yes',
    inputs: ['plan', 'tenure'],
    compartment: 'us-west',
    status: 'proposed',
    evaluation: {
      kind: 'chance',
      known: 500,
      learned_from: 400,
      judged_on: 100,
      measure: 'chance error (Brier)',
      score: 0.081,
      naive_score: 0.2034,
      skill: 0.6,
      important: [
        { field: 'tenure', share: 0.7 },
        { field: 'plan', share: 0.3 },
      ],
      group_by: 'region',
      groups: [
        { value: 'US', records: 60, score: 0.05, skill: 0.75 },
        { value: 'BR', records: 32, score: 0.25, skill: -0.02 },
        { value: 'NZ', records: 8, score: null, skill: null },
      ],
      share_right: 0.9,
    },
    provenance: { library: 'scikit-learn 1.9.1', seed: 0, records: 520 },
    current: true,
    refusal: null,
    proposed_at: '2026-10-17T09:00:00+00:00',
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('reviewing a predicted field (R48)', () => {
  it('says what the field holds, and the score against the naive guess on records it did not learn from', async () => {
    mockedList.mockResolvedValue([proposal()])
    render(<PredictionReview onSessionExpired={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'Customer Churn risk' })
    expect(
      within(card).getByText(
        'Fills Churn risk with the chance, 0 to 1, that Churned is "yes", only where Churned is not known, learning from plan, tenure.',
      ),
    ).toBeInTheDocument()
    expect(
      within(card).getByText(/On 100 known records it did not learn from \(it learned from 400\)/),
    ).toBeInTheDocument()
    expect(
      within(card).getByText(/chance error \(Brier\) 0\.081, against 0\.203 for the naive guess/),
    ).toBeInTheDocument()
    expect(within(card).getByText('60%')).toBeInTheDocument()
    expect(within(card).getByText(/scikit-learn 1\.9\.1 on 520 records in us-west/)).toBeInTheDocument()
  })

  it('breaks the score down by group, says which are too few, and names a group it fails', async () => {
    mockedList.mockResolvedValue([proposal()])
    render(<PredictionReview onSessionExpired={vi.fn()} />)

    const card = await screen.findByRole('article', { name: 'Customer Churn risk' })
    expect(within(card).getByRole('heading', { name: 'By region' })).toBeInTheDocument()
    const rows = within(card).getAllByRole('row')
    expect(rows.map((row) => row.textContent)).toEqual([
      'regionRecords judgedSkill',
      'US6075%',
      'BR32-2%',
      'NZ8too few to judge',
    ])
    expect(within(card).getByText(/No better than guessing for BR/)).toBeInTheDocument()
    expect(within(card).getByText('tenure 70% · plan 30%')).toBeInTheDocument()
  })

  it('a class or a number reads in its own words', () => {
    expect(holdsSentence(proposal({ kind: 'class', chance_of: null }))).toMatch(/with the most likely Churned,/)
    expect(holdsSentence(proposal({ kind: 'number', chance_of: null }))).toMatch(/with a likely Churned,/)
    const accuracy = proposal({
      evaluation: { ...proposal().evaluation, kind: 'class', measure: 'share right', score: 0.91, naive_score: 0.7 },
    })
    expect(scoreSentence(accuracy)).toMatch(/share right 91%, against 70%/)
  })

  it('shows a too-good-to-be-true warning', async () => {
    mockedList.mockResolvedValue([
      proposal({ evaluation: { ...proposal().evaluation, warning: "Too good to be true: check 'cancelled' first." } }),
    ])
    render(<PredictionReview onSessionExpired={vi.fn()} />)
    expect(await screen.findByText(/Too good to be true/)).toBeInTheDocument()
  })

  it('approving sends the decision and shows it decided', async () => {
    mockedList.mockResolvedValue([proposal()])
    mockedDecide.mockResolvedValue(
      proposal({ status: 'approved', decided_by: 'ops', decided_at: '2026-10-17T10:00:00+00:00' }),
    )
    render(<PredictionReview onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))
    await waitFor(() => expect(mockedDecide).toHaveBeenCalledWith('p1', true))
    expect(await screen.findByText('approved')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
  })

  it('one that cannot be approved says why, and offers only Reject', async () => {
    mockedList.mockResolvedValue([proposal({ refusal: 'no better than the naive guess (skill -5%).' })])
    render(<PredictionReview onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Cannot be approved: no better than the naive guess/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('a changed question offers no decision', async () => {
    mockedList.mockResolvedValue([proposal({ current: false })])
    render(<PredictionReview onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/question has changed/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Reject' })).not.toBeInTheDocument()
  })

  it('nothing to review says where proposals come from', async () => {
    mockedList.mockResolvedValue([])
    render(<PredictionReview onSessionExpired={vi.fn()} />)
    expect(await screen.findByText('No predictions to review')).toBeInTheDocument()
  })
})
