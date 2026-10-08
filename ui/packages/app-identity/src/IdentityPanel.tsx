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

import { getMergeProposals, type MergeProposal } from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
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
      {(proposals) => {
        const pending = proposals.filter((proposal) => proposal.decision === 'pending')
        return (
          <>
            <p className="identity__lede">
              Pairs the matcher believes may be the same thing. Nothing here has changed any data: a decision is
              recorded, and the next build consults it.
            </p>
            {proposals.length === 0 && <Notice state="neutral">No proposed merges.</Notice>}
            {proposals.length > 0 && pending.length === 0 && (
              <Notice state="granted">Every proposal has been decided.</Notice>
            )}

            {proposals.map((proposal) => (
              <ProposalCard
                key={proposal.proposal_id}
                proposal={proposal}
                onDecided={onDecided}
                onSessionExpired={onSessionExpired}
              />
            ))}
          </>
        )
      }}
    </AsyncPanel>
  )
}
