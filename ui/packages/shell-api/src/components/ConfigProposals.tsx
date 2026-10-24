/**
 * Configuration changes waiting for a second person (decided 16
 * October): access labels that would let anyone read more, and earlier
 * versions put back that would.
 *
 * FOR THE APPROVER, everything they are agreeing to in one card: what it
 * is, who asked and WHY (in their words), what it does to every role it
 * touches -- recomputed against what runs now, not what ran when it was
 * proposed -- and the exact lines of each file. A change whose files
 * have moved since says so; approving it would be refused, because the
 * approver would be agreeing to a merge nobody reviewed.
 *
 * THE SERVER DECIDES WHO MAY: approving needs manage:roles and not
 * being the proposer; a proposer may withdraw their own. The buttons
 * follow the same rules so nobody is offered a refusal, and the server
 * holds them regardless.
 */

import { Button, Card } from '@blueprintjs/core'
import {
  approveConfigProposal,
  type ConfigProposal,
  getConfigProposals,
  getCurrentUser,
  getErrorMessage,
  handleIfSessionExpired,
  rejectConfigProposal,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import FileDiff from '@elysium/shell-api/components/FileDiff'
import Notice from '@elysium/shell-api/components/Notice'
import { ConfigImpact } from '@elysium/shell-api/components/RoleImpact'
import StatusTag from '@elysium/shell-api/components/StatusTag'
import { useEffect, useRef, useState } from 'react'

const KIND = { labels: 'access labels', restore: 'earlier version' } as const

export default function ConfigProposals({
  onSessionExpired,
  showEmpty = false,
}: {
  onSessionExpired: () => void
  /** Say "nothing is waiting" rather than render nothing. */
  showEmpty?: boolean
}) {
  const [proposals, setProposals] = useState<ConfigProposal[] | null>(null)
  const [me, setMe] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState<string | null>(null)
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = () => {
    Promise.all([getConfigProposals(), getCurrentUser()])
      .then(([waiting, user]) => {
        setProposals(waiting)
        setMe((user as { username?: string }).username ?? null)
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        // NOT THEIRS TO SEE: neither managing roles nor the deployment.
        setProposals(null)
      })
  }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(load, [])

  const act = (id: string, run: () => Promise<string>) => {
    setBusy(id)
    setError(null)
    setNotice(null)
    run()
      .then((said) => {
        setNotice(said)
        load()
      })
      .catch((caught: unknown) => {
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setError(getErrorMessage(caught))
        load()
      })
      .finally(() => setBusy(null))
  }

  if (proposals === null) return null
  if (proposals.length === 0 && !showEmpty && notice === null) return null

  return (
    <section className="config-proposals" aria-label="Configuration changes waiting for approval">
      <h5 className="config-proposals__title">Configuration changes waiting</h5>
      {error !== null && <ErrorState>{error}</ErrorState>}
      {notice !== null && <Notice state="granted">{notice}</Notice>}
      {proposals.length === 0 && <p className="roles__empty">Nothing is waiting.</p>}
      {proposals.map((proposal) => {
        const own = proposal.proposed_by === me
        return (
          <Card key={proposal.proposal_id} className="roles__change">
            <div className="roles__change-head">
              <strong>{proposal.summary}</strong>
              <StatusTag>{KIND[proposal.kind]}</StatusTag>
              <span className="roles__by">proposed by {proposal.proposed_by}</span>
            </div>
            <p className="config-proposals__reason">
              <span className="config-proposals__why">Why:</span> {proposal.reason}
            </p>
            {proposal.stale && (
              <Notice state="pending" title="The configuration has changed since">
                This no longer describes what approving it would do, so approving is refused. It needs proposing again.
              </Notice>
            )}
            {proposal.problem !== null && <ErrorState>{proposal.problem}</ErrorState>}
            {proposal.impact && <ConfigImpact impact={proposal.impact} />}
            <FileDiff lines={proposal.diff} label={`Changes proposed by ${proposal.proposed_by}`} />
            <div className="roles__decide">
              <Button
                intent="primary"
                disabled={own || proposal.stale}
                loading={busy === proposal.proposal_id}
                title={own ? 'You proposed this; somebody else must approve it.' : undefined}
                onClick={() =>
                  act(proposal.proposal_id, async () => {
                    const result = await approveConfigProposal(proposal.proposal_id)
                    return `Applied; the deployment reloaded as generation ${result.to_generation}.`
                  })
                }
              >
                Approve
              </Button>
              <Button
                onClick={() =>
                  act(proposal.proposal_id, async () => {
                    const result = await rejectConfigProposal(proposal.proposal_id)
                    return result.status === 'withdrawn' ? 'Withdrawn.' : 'Rejected.'
                  })
                }
              >
                {own ? 'Withdraw' : 'Reject'}
              </Button>
            </div>
          </Card>
        )
      })}
    </section>
  )
}
