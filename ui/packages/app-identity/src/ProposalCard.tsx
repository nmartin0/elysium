/**
 * One proposed merge, and the decision a person makes about it.
 *
 * IN ITS OWN FILE, like every other component in this workspace. It
 * began inside IdentityPanel.tsx and nothing rendered: a populated
 * list produced an empty container with no thrown error and nothing on
 * console.error, while an empty list rendered correctly. Splitting it
 * also matches the convention -- every package here is one component
 * per file with its test beside it.
 */

import { useCallback, useState } from 'react'
import { Checkbox } from '@blueprintjs/core'

import {
  decideMergeProposal,
  handleIfSessionExpired,
  type MatchProvenance,
  type MergeProposal,
} from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import DataTable from '@elysium/shell-api/components/DataTable'

/** The verdicts masked_comparison emits, as a tag state. */
const VERDICT_STATE = {
  agree: 'granted',
  differ: 'refused',
  'one side missing': 'pending',
  'both missing': 'neutral',
} as const

function verdictState(verdict: string) {
  return VERDICT_STATE[verdict as keyof typeof VERDICT_STATE] ?? 'neutral'
}

export default function ProposalCard({
  proposal,
  selected = false,
  onToggle,
  onDecided,
  onSessionExpired,
}: {
  proposal: MergeProposal
  /** Ticked for the queue's bulk approval (WIRED-3). */
  selected?: boolean
  onToggle?: () => void
  onDecided: () => void
  onSessionExpired: () => void
}) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const decide = useCallback(
    async (decision: 'approved' | 'rejected') => {
      setBusy(true)
      setError(null)
      try {
        // THE GROUP SHOWN ON THIS CARD, confirmed by approving it (R58).
        await decideMergeProposal(
          proposal.proposal_id,
          decision,
          undefined,
          decision === 'approved' ? proposal.group : undefined,
        )
        onDecided()
      } catch (caught) {
        // A 401 HERE IS NOT AN ERROR TO SHOW. The session went while
        // the reviewer was deciding; rendering "401" beside a merge
        // they are mid-judgement on tells them nothing and leaves them
        // on a dead screen. sessionExpiry.test.ts enforces this across
        // every panel that catches.
        if (!handleIfSessionExpired(caught, onSessionExpired)) {
          setError(caught instanceof Error ? caught.message : String(caught))
        }
      } finally {
        setBusy(false)
      }
    },
    [proposal.proposal_id, proposal.group, onDecided, onSessionExpired],
  )

  const settled = proposal.decision !== 'pending'
  const group = proposal.group && proposal.group.length > 0 ? proposal.group : null

  return (
    <section className="identity__proposal" aria-label={`Merge ${proposal.left_id} and ${proposal.right_id}`}>
      <header className="identity__head">
        <h3>
          {proposal.object_type} {proposal.left_id} and {proposal.right_id}
        </h3>
        {/* ONE GROUP, so the header's space-between keeps both tags at
            the right edge rather than floating the first mid-row --
            seen in the browser. */}
        <span className="identity__tags">
          {!settled && proposal.high_confidence && (
            <StatusTag state="granted">
              {proposal.preselected_by === 'calibrated' ? 'calibrated pick' : 'high confidence'}
            </StatusTag>
          )}
          <StatusTag state={settled ? (proposal.decision === 'approved' ? 'granted' : 'refused') : 'pending'}>
            {proposal.decision}
          </StatusTag>
        </span>
      </header>

      {!settled && onToggle && (
        <Checkbox
          className="identity__select"
          checked={selected}
          onChange={onToggle}
          label="Include in bulk approval"
        />
      )}

      <p className="identity__pattern">
        Agreement pattern: <code className="mono">{proposal.pattern}</code>
      </p>

      <DataTable className="identity__fields">
        <thead>
          <tr>
            <th scope="col">Field</th>
            <th scope="col">Verdict</th>
            <th scope="col">{proposal.left_id}</th>
            <th scope="col">{proposal.right_id}</th>
          </tr>
        </thead>
        <tbody>
          {proposal.fields.map((field) => (
            <tr key={field.field}>
              <td>{field.field}</td>
              <td>
                <StatusTag state={verdictState(field.verdict)}>{field.verdict}</StatusTag>
              </td>
              {/* NOTHING is rendered for a withheld value -- not a dash,
                  not a placeholder. The value was never sent. */}
              <td>{field.left}</td>
              <td>{field.right}</td>
            </tr>
          ))}
        </tbody>
      </DataTable>

      {proposal.withheld.length > 0 && (
        <Notice state="neutral">
          Compared on {proposal.withheld.length} further {proposal.withheld.length === 1 ? 'field' : 'fields'} you may
          not read: {proposal.withheld.join(', ')}. The verdicts above include them.
        </Notice>
      )}

      {proposal.provenance && <WhatProducedIt provenance={proposal.provenance} />}

      {!settled && group && <WouldJoin proposal={proposal} group={group} />}

      {error && <ErrorState>{error}</ErrorState>}

      {!settled && (
        <div className="identity__actions">
          <Action
            tone="primary"
            text={group ? `Approve the group of ${group.length + (proposal.group_hidden ?? 0)}` : 'Same entity'}
            disabled={busy}
            onClick={() => void decide('approved')}
          />
          <Action tone="danger" text="Not the same" disabled={busy} onClick={() => void decide('rejected')} />
        </div>
      )}

      {settled && proposal.decided_by && <p className="identity__decided">Decided by {proposal.decided_by}.</p>}
    </section>
  )
}

/**
 * WHAT APPROVING THIS WOULD JOIN (R58), when it is more than the pair.
 *
 * Merges chain: approving A with B while B with C stands approved makes
 * all three one entity, and A with C is a pair nobody was shown. This is
 * Informatica MDM's "pre-merge review" -- a merge that would join
 * clusters is flagged, not made, until somebody looks at the whole
 * group -- and the reason the button says how many it approves.
 */
function WouldJoin({ proposal, group }: { proposal: MergeProposal; group: string[] }) {
  const others = group.filter((name) => name !== proposal.left_id && name !== proposal.right_id)
  const hidden = proposal.group_hidden ?? 0
  return (
    <Notice state="pending">
      Approving this makes {group.length + hidden} records one {proposal.object_type}, not two: it also joins{' '}
      {others.join(', ')}
      {hidden > 0 &&
        `${others.length > 0 ? ', and ' : ''}${hidden} ${hidden === 1 ? 'record' : 'records'} you cannot see`}
      , through merges already approved. Some of these pairs were never compared with each other.
    </Notice>
  )
}

/**
 * WHAT PRODUCED THIS PROPOSAL (R62), so a decision can still be explained
 * after the settings change. Collapsed: it is the follow-up question, not
 * the decision.
 *
 * NO NUMBERS ON THIS SCREEN, by the same rule that keeps the score off
 * it: "the reviewer's decision is made on the agreement PATTERN, not the
 * score", and a weight or a threshold beside a pair invites the same
 * deference. They are recorded with the proposal and returned by the API
 * for whoever audits a decision; the reviewer is told which matcher, what
 * it compared, and what it required to agree.
 */
function WhatProducedIt({ provenance }: { provenance: MatchProvenance }) {
  const matcher = [provenance.matcher, provenance.version].filter(Boolean).join(' ')
  return (
    <details className="identity__provenance">
      <summary>What produced this proposal</summary>
      <dl>
        {matcher && (
          <>
            <dt>Matcher</dt>
            <dd>{matcher}, with weights this deployment declared</dd>
          </>
        )}
        {provenance.compare && (
          <>
            <dt>Compared</dt>
            <dd>{provenance.compare.join(', ')}</dd>
          </>
        )}
        {provenance.block_on && (
          <>
            <dt>Only pairs agreeing on</dt>
            <dd>{provenance.block_on.join(', ')}</dd>
          </>
        )}
      </dl>
    </details>
  )
}
