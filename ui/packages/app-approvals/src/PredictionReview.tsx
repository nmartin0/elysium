/**
 * A predicted field's measurement, for a person to approve (R48; the
 * owner, 17 October).
 *
 * WHAT THE APPROVER NEEDS, AND IN THIS ORDER: what the field will hold;
 * how the model did on records it NEVER learned from, against the naive
 * guess -- skill, where 0% is no better than guessing; the same score
 * per group of the field chosen when it was proposed, because an average
 * can hide a group it fails; which inputs it leans on; and any warning.
 *
 * AGGREGATES ONLY. No record, and no model: the server keeps neither.
 * Approving lets the sync train it again, measure again, and fill the
 * field where the answer is not known.
 *
 * NOT OFFERED WHEN IT CANNOT BE APPROVED -- no better than guessing, no
 * group breakdown, or a question that has changed -- and the panel says
 * why. The server refuses it too.
 */

import { Button } from '@blueprintjs/core'
import {
  decidePredictionProposal,
  getErrorMessage,
  getPredictionProposals,
  handleIfSessionExpired,
  type PredictionProposal,
} from '@elysium/shell-api/api'
import DataTable from '@elysium/shell-api/components/DataTable'
import EmptyState from '@elysium/shell-api/components/EmptyState'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag, { type TagState } from '@elysium/shell-api/components/StatusTag'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import { useState } from 'react'

const STATUS_TAG: Record<PredictionProposal['status'], TagState> = {
  proposed: 'pending',
  approved: 'granted',
  rejected: 'refused',
  superseded: 'neutral',
}

function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`
}

function number(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : String(Number(value.toPrecision(3)))
}

/** What the field will hold, in a sentence. */
export function holdsSentence(proposal: PredictionProposal): string {
  const what =
    proposal.kind === 'chance'
      ? `the chance, 0 to 1, that ${proposal.target_label} is "${proposal.chance_of}"`
      : proposal.kind === 'class'
        ? `the most likely ${proposal.target_label}`
        : `a likely ${proposal.target_label}`
  return (
    `Fills ${proposal.field_label} with ${what}, only where ${proposal.target_label} is not known, ` +
    `learning from ${proposal.inputs.join(', ')}.`
  )
}

/** How it did on records it did not learn from, in a sentence. */
export function scoreSentence(proposal: PredictionProposal): string {
  const evaluation = proposal.evaluation
  const shown = (value: number) => (evaluation.kind === 'class' ? percent(value) : number(value))
  const right =
    evaluation.share_right !== undefined
      ? ` Read as yes-or-no at an even chance, ${percent(evaluation.share_right)} right.`
      : ''
  return (
    `On ${evaluation.judged_on} known records it did not learn from (it learned from ${evaluation.learned_from}): ` +
    `${evaluation.measure} ${shown(evaluation.score)}, against ${shown(evaluation.naive_score)} for the naive guess.` +
    right
  )
}

function ProposalCard({
  proposal,
  onDecided,
  onSessionExpired,
}: {
  proposal: PredictionProposal
  onDecided: (next: PredictionProposal) => void
  onSessionExpired: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const evaluation = proposal.evaluation
  const waiting = proposal.status === 'proposed' && proposal.current
  const failing = (evaluation.groups ?? []).filter((group) => group.skill !== null && group.skill <= 0)

  async function decide(approve: boolean) {
    setBusy(true)
    setError(null)
    try {
      onDecided(await decidePredictionProposal(proposal.proposal_id, approve))
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <article className="enrichment-recipe" aria-label={`${proposal.object_type} ${proposal.field_label}`}>
      <header className="enrichment-recipe__head">
        <h3>
          {proposal.object_type} · {proposal.field_label}
        </h3>
        <StatusTag state={STATUS_TAG[proposal.status]}>{proposal.status}</StatusTag>
      </header>
      <p className="enrichment-recipe__question">{holdsSentence(proposal)}</p>

      <p className="enrichment-recipe__score">{scoreSentence(proposal)}</p>
      <p className="enrichment-recipe__meta">
        Skill <strong>{percent(evaluation.skill)}</strong>: how much of the way from the naive guess to never wrong it
        gets. 0% is no better than guessing.
      </p>
      {evaluation.warning && <Notice state="pending">{evaluation.warning}</Notice>}

      {evaluation.groups && (
        <>
          <h4>By {evaluation.group_by}</h4>
          <DataTable>
            <thead>
              <tr>
                <th>{evaluation.group_by}</th>
                <th className="data-table__num">Records judged</th>
                <th className="data-table__num">Skill</th>
              </tr>
            </thead>
            <tbody>
              {evaluation.groups.map((group) => (
                <tr key={group.value}>
                  <td>{group.value}</td>
                  <td className="data-table__num">{group.records}</td>
                  <td className="data-table__num">
                    {group.skill === null ? 'too few to judge' : percent(group.skill)}
                  </td>
                </tr>
              ))}
            </tbody>
          </DataTable>
          {failing.length > 0 && (
            <Notice state="pending">
              No better than guessing for {failing.map((group) => group.value).join(', ')}: its guesses there would be
              noise.
            </Notice>
          )}
        </>
      )}

      <h4>What it leans on</h4>
      <p className="enrichment-recipe__meta">
        {evaluation.important.map((item) => `${item.field} ${percent(item.share)}`).join(' · ')}
      </p>

      <p className="enrichment-recipe__provenance">
        Trained with {proposal.provenance.library ?? 'scikit-learn'} on {proposal.provenance.records ?? '?'} records
        {proposal.compartment !== null ? ` in ${proposal.compartment}` : ''}, proposed{' '}
        {formatTimestamp(proposal.proposed_at)}
        {proposal.decided_by && proposal.decided_at
          ? `; ${proposal.status} by ${proposal.decided_by} ${formatTimestamp(proposal.decided_at)}`
          : ''}
        .
      </p>

      {proposal.status === 'proposed' && !proposal.current && (
        <Notice state="neutral">
          The field's question has changed since this was trained, so it can no longer be approved. Propose it again.
        </Notice>
      )}
      {waiting && proposal.refusal && <Notice state="neutral">Cannot be approved: {proposal.refusal}</Notice>}
      {error && <ErrorState>{error}</ErrorState>}
      {waiting && (
        <div className="enrichment-recipe__actions">
          {!proposal.refusal && (
            <Button intent="primary" loading={busy} onClick={() => void decide(true)}>
              Approve
            </Button>
          )}
          <Button loading={busy} onClick={() => void decide(false)}>
            Reject
          </Button>
          {!proposal.refusal && (
            <span className="enrichment-recipe__after">
              Approving lets the next sync train it again and fill {proposal.field_label}; if it then measures worse,
              the field stays empty.
            </span>
          )}
        </div>
      )}
    </article>
  )
}

export default function PredictionReview({ onSessionExpired }: { onSessionExpired: () => void }) {
  const { data, error } = useFetchOnce<PredictionProposal[]>(getPredictionProposals, onSessionExpired)
  const [decided, setDecided] = useState<Record<string, PredictionProposal>>({})

  if (error) return <ErrorState>{error}</ErrorState>
  if (data === null) return <LoadingState />

  const proposals = data.map((proposal) => decided[proposal.proposal_id] ?? proposal)
  const isWaiting = (proposal: PredictionProposal) => proposal.status === 'proposed' && proposal.current
  const waiting = proposals.filter(isWaiting)
  const rest = proposals.filter((proposal) => !isWaiting(proposal))
  const card = (proposal: PredictionProposal) => (
    <ProposalCard
      key={proposal.proposal_id}
      proposal={proposal}
      onSessionExpired={onSessionExpired}
      onDecided={(next) => setDecided((current) => ({ ...current, [next.proposal_id]: next }))}
    />
  )

  if (proposals.length === 0) {
    return (
      <EmptyState
        icon="predictive-analysis"
        title="No predictions to review"
        reason="Predictions appear here when someone proposes a predicted field, and only for fields you may read, in your own compartment."
      />
    )
  }
  return (
    <div className="enrichment-review">
      {waiting.length > 0 ? (
        waiting.map(card)
      ) : (
        <p className="enrichment-review__none">Nothing is waiting for a decision.</p>
      )}
      {rest.length > 0 && (
        <section className="enrichment-review__decided">
          <h3>Decided, or for a question that has changed</h3>
          {rest.map(card)}
        </section>
      )}
    </div>
  )
}
