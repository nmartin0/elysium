/**
 * The Inbox counts, kept current while the shell is open (DEV_UI 15.3).
 *
 * "PRESENCE WITHOUT PROMPTING": the number is always on screen and
 * nothing pops up. It is re-read when the reader moves (`refreshKey`,
 * the shell passes its location) -- deciding something in the Inbox
 * and moving on should not leave a stale count behind -- and once a
 * minute otherwise, while the tab is visible.
 *
 * AND AT ONCE WHEN THE SERVER SAYS SO (16 October): the live-update
 * stream now carries "your inbox changed" to its owner alone, sent when
 * the server writes them a notification -- a trigger firing at its
 * window's edge, or after a saved change. The minute's poll stays for
 * everything that stream does not carry: approvals proposed, and
 * notifications written by the sync, which is another process.
 *
 * QUIET ON FAILURE: a badge that cannot be read is absent, not an
 * error on every screen.
 */

import { useEffect, useRef, useState } from 'react'

import { getInboxCounts, type InboxCounts } from './api'
import { subscribeToInbox } from './liveUpdates'

const EVERY_MS = 60_000

export function useInboxCounts(refreshKey: string): InboxCounts | null {
  const [counts, setCounts] = useState<InboxCounts | null>(null)
  const alive = useRef(true)

  useEffect(() => {
    alive.current = true
    const read = () => {
      if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return
      getInboxCounts()
        .then((next) => {
          if (alive.current) setCounts(next)
        })
        .catch(() => {
          // Absent rather than wrong; see the header.
        })
    }
    read()
    const timer = setInterval(read, EVERY_MS)
    const unsubscribe = subscribeToInbox(read)
    return () => {
      alive.current = false
      clearInterval(timer)
      unsubscribe()
    }
  }, [refreshKey])

  return counts
}

/** The number the header shows: decisions and unread notices. */
export function totalWaiting(counts: InboxCounts | null): number {
  // `?? 0` for a server that predates the field, so the badge is a
  // number rather than NaN while a deployment is mid-upgrade.
  return counts === null
    ? 0
    : counts.approvals +
        counts.notifications +
        counts.identity +
        (counts.enrichment ?? 0) +
        (counts.predictions ?? 0) +
        (counts.unusual ?? 0)
}
