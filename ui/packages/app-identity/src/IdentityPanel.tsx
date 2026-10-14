/**
 * Proposed merges, and the decision a person makes about them.
 *
 * WHY THIS SCREEN DID NOT EXIST. `core/mirror/matching.py` proposes
 * that two entities might be one, `core/identity_decisions.py` records
 * what was decided, and `core/masked_review.py` shows a reviewer the
 * verdict without the value. All three were built and tested, and
 * nothing reached them -- 580 lines of finished feature with no route
 * and no screen until now.
 *
 * WHAT A REVIEWER IS SHOWN, and why it looks sparse. They decide on
 * the AGREEMENT PATTERN, not on values and not on a score.
 * FUSION_AND_IDENTITY.md is explicit that "the reviewer's decision is
 * made on the agreement PATTERN, not the score", and the route does
 * not send a score at all: a number invites deference to the matcher,
 * which is the thing a human review exists to prevent.
 *
 * A WITHHELD VALUE IS ABSENT, NOT BLANK. The server never serialises a
 * field this caller may not read, so `left` and `right` are
 * `undefined` rather than null or empty. This renders nothing in their
 * place -- no dash, no asterisks, no "hidden" label on the value
 * itself. The withheld FIELD NAMES are listed once, separately, so a
 * reviewer knows the comparison was wider than what they can see
 * without the screen implying there is a value behind a mask.
 *
 * APPROVING IS A WRITE. The route requires `write:<Type>`, so a
 * reviewer with read access can work the queue and will be refused at
 * the decision. The refusal is shown rather than the buttons being
 * hidden: a reviewer who cannot decide should know the queue is real
 * and that someone else must act, not silently see a list that does
 * nothing.
 */

import { useState } from 'react'

import {
  decideMergeProposal,
  getMergeProposals,
  handleIfSessionExpired,
  type MergeProposal,
} from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import Notice from '@elysium/shell-api/components/Notice'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'

import ProposalCard from './ProposalCard'

export default function IdentityPanel({ onSessionExpired }: { onSessionExpired: () => void }) {
  /**
   * `useFetchOnce` fetches once and does not expose a refetch, which is
   * correct for the panels it was written for. A decision here changes
   * the list, so the whole panel is remounted by key instead -- cruder
   * than a refetch and honest about it, rather than adding a second
   * fetching path to a hook whose whole point is that it runs once.
   */
  const [generation, setGeneration] = useState(0)
  return (
    <IdentityQueue
      key={generation}
      onSessionExpired={onSessionExpired}
      onDecided={() => setGeneration((count) => count + 1)}
    />
  )
}

function IdentityQueue({ onSessionExpired, onDecided }: { onSessionExpired: () => void; onDecided: () => void }) {
  const { data: proposals, error } = useFetchOnce<MergeProposal[]>(() => getMergeProposals(), onSessionExpired)

  return (
    <AsyncPanel error={error} data={proposals}>
      {(proposals) => <ProposalList proposals={proposals} onDecided={onDecided} onSessionExpired={onSessionExpired} />}
    </AsyncPanel>
  )
}

/**
 * The queue, and the selection a bulk approval acts on (WIRED-3).
 *
 * PRE-SELECTED, NEVER APPLIED. A proposal at or above its type's
 * `auto_propose_above` arrives ticked, the owner's decision of 14 Oct:
 * the matcher may do the sorting, a person still does the approving.
 * The selection starts from the server's flag once, when the list
 * arrives, and is the reviewer's after that -- unticking one is final.
 *
 * ONE REQUEST PER PROPOSAL, in turn, rather than a bulk endpoint: each
 * approval is its own `write:<Type>` decision on the server, and a
 * refusal of one must not hide that the others went through.
 */
function ProposalList({
  proposals,
  onDecided,
  onSessionExpired,
}: {
  proposals: MergeProposal[]
  onDecided: () => void
  onSessionExpired: () => void
}) {
  const pending = proposals.filter((proposal) => proposal.decision === 'pending')
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(pending.filter((proposal) => proposal.high_confidence).map((proposal) => proposal.proposal_id)),
  )
  const [busy, setBusy] = useState(false)
  const [failures, setFailures] = useState<string[]>([])
  const [attempted, setAttempted] = useState(0)

  const toggle = (proposalId: string) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(proposalId)) next.delete(proposalId)
      else next.add(proposalId)
      return next
    })

  const approveSelected = async () => {
    setBusy(true)
    const refused: string[] = []
    for (const proposal of pending.filter((each) => selected.has(each.proposal_id))) {
      try {
        await decideMergeProposal(proposal.proposal_id, 'approved')
      } catch (caught) {
        if (handleIfSessionExpired(caught, onSessionExpired)) return
        // NAMED BY THE PAIR, not the proposal's internal id -- the first
        // version printed a UUID nobody could act on (seen in the browser).
        refused.push(
          `${proposal.left_id} and ${proposal.right_id}: ${caught instanceof Error ? caught.message : String(caught)}`,
        )
      }
    }
    setBusy(false)
    setAttempted(selected.size)
    if (refused.length > 0) setFailures(refused)
    else onDecided()
  }

  const highConfidence = pending.filter((proposal) => proposal.high_confidence).length

  return (
    <>
      <p className="identity__lede">
        Pairs the matcher believes may be the same thing. Nothing here has changed any data: a decision is recorded, and
        the next build consults it.
      </p>
      {proposals.length === 0 && <Notice state="neutral">No proposed merges.</Notice>}
      {proposals.length > 0 && pending.length === 0 && (
        <Notice state="granted">Every proposal has been decided.</Notice>
      )}

      {pending.length > 0 && (
        <div className="identity__bulk">
          <span>
            {selected.size} of {pending.length} selected
            {highConfidence > 0 && ` (${highConfidence} pre-selected as high confidence)`}
          </span>
          <Action
            tone="primary"
            text={`Approve ${selected.size} selected`}
            disabled={busy || selected.size === 0}
            onClick={() => void approveSelected()}
          />
        </div>
      )}
      {failures.length > 0 && (
        <ErrorState
          title={
            failures.length === attempted
              ? `None of the ${attempted} could be approved`
              : `${failures.length} of ${attempted} could not be approved; the rest were`
          }
        >
          <ul>
            {failures.map((failure) => (
              <li key={failure}>{failure}</li>
            ))}
          </ul>
        </ErrorState>
      )}

      {proposals.map((proposal) => (
        <ProposalCard
          key={proposal.proposal_id}
          proposal={proposal}
          selected={selected.has(proposal.proposal_id)}
          onToggle={() => toggle(proposal.proposal_id)}
          onDecided={onDecided}
          onSessionExpired={onSessionExpired}
        />
      ))}
    </>
  )
}
