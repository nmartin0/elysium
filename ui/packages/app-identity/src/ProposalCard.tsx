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
import { HTMLTable } from '@blueprintjs/core'

import { decideMergeProposal, handleIfSessionExpired, type MergeProposal } from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import Notice from '@elysium/shell-api/components/Notice'
import StatusTag from '@elysium/shell-api/components/StatusTag'

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
  onDecided,
  onSessionExpired,
}: {
  proposal: MergeProposal
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
        await decideMergeProposal(proposal.proposal_id, decision)
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
    [proposal.proposal_id, onDecided, onSessionExpired],
  )

  const settled = proposal.decision !== 'pending'

  return (
    <section className="identity__proposal" aria-label={`Merge ${proposal.left_id} and ${proposal.right_id}`}>
      <header className="identity__head">
        <h3>
          {proposal.object_type} {proposal.left_id} and {proposal.right_id}
        </h3>
        <StatusTag state={settled ? (proposal.decision === 'approved' ? 'granted' : 'refused') : 'pending'}>
          {proposal.decision}
        </StatusTag>
      </header>

      <p className="identity__pattern">
        Agreement pattern: <code className="mono">{proposal.pattern}</code>
      </p>

      <HTMLTable compact striped className="identity__fields">
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
      </HTMLTable>

      {proposal.withheld.length > 0 && (
        <Notice state="neutral">
          Compared on {proposal.withheld.length} further {proposal.withheld.length === 1 ? 'field' : 'fields'} you may
          not read: {proposal.withheld.join(', ')}. The verdicts above include them.
        </Notice>
      )}

      {error && <ErrorState>{error}</ErrorState>}

      {!settled && (
        <div className="identity__actions">
          <Action tone="primary" text="Same entity" disabled={busy} onClick={() => void decide('approved')} />
          <Action tone="danger" text="Not the same" disabled={busy} onClick={() => void decide('rejected')} />
        </div>
      )}

      {settled && proposal.decided_by && <p className="identity__decided">Decided by {proposal.decided_by}.</p>}
    </section>
  )
}
