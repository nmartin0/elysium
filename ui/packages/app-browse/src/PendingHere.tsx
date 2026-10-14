/**
 * A change waiting for approval, shown where it would land (DEV_UI 15.3).
 *
 * "SHOW PENDING PROPOSALS IN CONTEXT, which is the part no inbox does
 * well. If an object has a pending change, that belongs ON THE OBJECT;
 * if a set does, it belongs on the set -- '3 of these 40 have pending
 * changes'." And it is "the antidote to context-free approving, since the
 * reviewer is already looking at the thing being changed".
 *
 * Two shapes: on an object, which actions are waiting and whose decision
 * each is; on a set, how many of the objects shown have one. Both link
 * to the Inbox, where the change itself can be read and decided. The
 * server decides what the caller may know (the Inbox's own rule); this
 * only says it.
 *
 * QUIET ON FAILURE: a marker that cannot be read is absent, not an error
 * on top of the object.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getPendingFor, type PendingFor } from '@elysium/shell-api/api'
import Notice from '@elysium/shell-api/components/Notice'

/** The waiting writes for these ids, re-read when the ids change. */
export function usePendingFor(objectType: string | null, ids: string[]): Record<string, PendingFor[]> {
  const key = objectType ? `${objectType}|${ids.join(',')}` : ''
  const [found, setFound] = useState<{ key: string; pending: Record<string, PendingFor[]> }>({ key: '', pending: {} })

  useEffect(() => {
    if (!key) return
    // THE IDS ARE READ BACK OUT OF THE KEY, which stands for both inputs:
    // a new array holding the same ids is the same key and does not
    // refetch.
    const [type = '', joined = ''] = key.split('|')
    let cancelled = false
    getPendingFor(type, joined ? joined.split(',') : [])
      .then((pending) => {
        if (!cancelled) setFound({ key, pending })
      })
      .catch(() => {
        // Absent rather than wrong; see the header.
      })
    return () => {
      cancelled = true
    }
  }, [key])

  // Only the answer for THIS set: switching type must not show the last
  // one's markers on the new rows.
  return found.key === key ? found.pending : {}
}

export function PendingOnObject({ pending }: { pending: PendingFor[] }) {
  if (pending.length === 0) return null
  const yours = pending.filter((write) => write.awaiting_your_review).length
  return (
    <Notice state="pending" className="object-detail__pending">
      {pending.length === 1 ? 'A change to this object is' : `${pending.length} changes to this object are`} waiting for
      approval: {[...new Set(pending.map((write) => write.action_type_name))].join(', ')}
      {yours > 0 &&
        (yours === pending.length ? ', and the decision is yours' : `; ${yours} of them are yours to decide`)}
      . <Link to="/inbox?tab=approvals">Open the Inbox</Link>
    </Notice>
  )
}

export function PendingInSet({ count, shown }: { count: number; shown: number }) {
  if (count === 0) return null
  return (
    <Link className="set-name__pending" to="/inbox?tab=approvals">
      {count} of these {shown} {count === 1 ? 'has a change' : 'have changes'} waiting
    </Link>
  )
}
