/**
 * ApprovalsPanel -- proposals waiting for a decision.
 *
 * WHY THIS IS ITS OWN SUB-APP rather than a tab inside Browse or
 * Admin. Foundry's equivalent is a separate application consolidating
 * "compliance, governance, and peer-review workflows", reachable
 * directly rather than only through their admin console. Browse is
 * object-centric and an inbox is about no particular object; Admin is
 * deployment-centric and gated on manage:users, which is the wrong
 * grant entirely -- approving a write is something an ordinary user
 * does.
 *
 * TWO CATEGORIES, following their inbox's "Your inbox" and "Created by
 * you" filters. A proposer who cannot approve their own write -- the
 * four-eyes case -- otherwise has no way to learn whether anyone has
 * looked at it, and a proposal that vanishes into silence is one
 * people stop making.
 *
 * THE DETAIL IS FETCHED ON DEMAND, not with the list. A diff needs the
 * current value of every changed field, which is a permission-checked
 * read per field per object; doing that for every row would cost
 * hundreds of reads to render a queue somebody is scanning rather than
 * reading.
 */

import { Button, Card, CardList, NonIdealState, Tag } from '@blueprintjs/core'
import { useCallback, useEffect, useState } from 'react'

import {
  type AwaitingWrite,
  confirmWrite,
  getAwaitingWrites,
  getErrorMessage,
  handleIfSessionExpired,
} from '@elysium/shell-api/api'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import Workspace from '@elysium/shell-api/components/Workspace'
import { formatTimestamp } from '@elysium/shell-api/format'
import type { SubAppProps } from '@elysium/shell-api/types'

import WriteDetail from './WriteDetail'

export default function ApprovalsPanel({ onSessionExpired }: SubAppProps) {
  const [writes, setWrites] = useState<AwaitingWrite[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [openWriteId, setOpenWriteId] = useState<string | null>(null)
  const [busyWriteId, setBusyWriteId] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setWrites(await getAwaitingWrites())
      setError(null)
    } catch (caught) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }, [onSessionExpired])

  useEffect(() => {
    void load()
  }, [load])

  async function decide(writeId: string, approved: boolean) {
    setBusyWriteId(writeId)
    try {
      await confirmWrite(writeId, approved)
      setOpenWriteId(null)
      await load()
    } catch (caught) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      // THE ERROR IS SHOWN, NOT SWALLOWED, and this is where the
      // interesting refusals surface: a four-eyes rule refusing a
      // self-approval, or a write whose field the ontology no longer
      // declares. Both are decisions the server made for a stated
      // reason, and the reviewer needs that reason rather than a
      // generic failure.
      // THE ORDER MATTERS AND I HAD IT WRONG. load() clears the error
      // on success -- reasonably, since a successful refresh means the
      // last one worked -- so setting an error and then reloading
      // wiped the message before it rendered. The reviewer saw the
      // decision fail with no explanation.
      //
      // Reload first, then set. The list is refreshed either way,
      // because a refused decision releases the reservation and the
      // write reappears -- see PendingWriteStore.reserved().
      await load()
      setError(getErrorMessage(caught))
    } finally {
      setBusyWriteId(null)
    }
  }

  return (
    <Workspace>
      <AsyncPanel data={writes} error={error}>
        {(loaded) =>
          loaded.length === 0 ? (
            <NonIdealState
              icon="inbox"
              title="Nothing waiting"
              description="Proposals you can decide on, and ones you have made, appear here."
            />
          ) : (
            <CardList className="approvals__list">
              {loaded.map((write) => (
                <Card key={write.write_id} className="approvals__item">
                  <div className="approvals__summary">
                    <p className="approvals__description">{write.description}</p>
                    <p className="approvals__meta">
                      {/* Relative under 24h, absolute with a named zone
                      beyond it -- the shared formatter, so an expiry
                      here reads the same as a sync time in Browse. */}
                      Proposed by {write.proposed_by}, {formatTimestamp(write.proposed_at)}
                      {' · expires '}
                      {formatTimestamp(write.expires_at)}
                    </p>
                  </div>

                  <div className="approvals__tags">
                    {/* BOTH CAN BE TRUE. A deployment with no four-eyes
                    rule lets someone approve their own write, and
                    showing one tag would misreport the other. */}
                    {/* UNAPPLYABLE REPLACES the invitation rather than
                        sitting beside it. Both can be true -- you may
                        hold the grant AND the write may be impossible
                        -- and showing them together invites a decision
                        that cannot be carried out. */}
                    {write.undeclared_fields.length > 0 ? (
                      <Tag intent="warning">Cannot be applied</Tag>
                    ) : (
                      write.awaiting_your_review && <Tag intent="primary">Awaiting your review</Tag>
                    )}
                    {write.proposed_by_you && <Tag minimal>Proposed by you</Tag>}
                  </div>

                  <div className="approvals__actions">
                    <Button
                      small
                      onClick={() => setOpenWriteId(openWriteId === write.write_id ? null : write.write_id)}
                    >
                      {openWriteId === write.write_id ? 'Hide changes' : 'View changes'}
                    </Button>
                    {/* ONLY WHERE THE SERVER SAYS SO. The confirm route
                    checks this again -- this is not the control, it is
                    the button not lying about what will happen. */}
                    {/* NO APPROVE on a write that cannot be applied:
                        confirm_and_execute() would refuse it, and a
                        button whose only outcome is a refusal wastes
                        a reviewer's decision. Reject stays below. */}
                    {write.awaiting_your_review && write.undeclared_fields.length === 0 && (
                      <>
                        <Button
                          small
                          intent="primary"
                          loading={busyWriteId === write.write_id}
                          onClick={() => void decide(write.write_id, true)}
                        >
                          Approve
                        </Button>
                      </>
                    )}
                    {/* REJECT STAYS even when a write cannot be
                        applied. A reviewer still needs to clear it out
                        of the queue, and a rejection is deliberately
                        never blocked by the criteria or the
                        unapplyable check -- otherwise a proposal
                        nobody can act on sits there until its TTL. */}
                    {write.awaiting_your_review && (
                      <Button
                        small
                        intent="danger"
                        loading={busyWriteId === write.write_id}
                        onClick={() => void decide(write.write_id, false)}
                      >
                        Reject
                      </Button>
                    )}
                  </div>

                  {openWriteId === write.write_id && (
                    <WriteDetail writeId={write.write_id} onSessionExpired={onSessionExpired} />
                  )}
                </Card>
              ))}
            </CardList>
          )
        }
      </AsyncPanel>
    </Workspace>
  )
}
