/**
 * The Inbox counts, kept current while the shell is open (DEV_UI 15.3).
 *
 * "PRESENCE WITHOUT PROMPTING": the number is always on screen and
 * nothing pops up. It is re-read when the reader moves (`refreshKey`,
 * the shell passes its location) -- deciding something in the Inbox
 * and moving on should not leave a stale count behind -- and once a
 * minute otherwise, while the tab is visible.
 *
 * WHY POLLING AND NOT THE LIVE-UPDATE STREAM: /api/events carries data
 * changes by type and verb, and nothing about queues. A write proposed
 * by a nightly automation would never reach the badge from there. A
 * minute is the "within a minute" a person would call current.
 *
 * QUIET ON FAILURE: a badge that cannot be read is absent, not an
 * error on every screen.
 */

import { useEffect, useRef, useState } from 'react'

import { getInboxCounts, type InboxCounts } from './api'

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
    return () => {
      alive.current = false
      clearInterval(timer)
    }
  }, [refreshKey])

  return counts
}

/** The number the header shows: decisions and unread notices. */
export function totalWaiting(counts: InboxCounts | null): number {
  return counts === null ? 0 : counts.approvals + counts.notifications + counts.identity
}
