/**
 * THE INBOX'S BADGE (BLOCKING.md item 3, step 1.3c): how much is waiting,
 * on the Inbox's rail entry, on every screen (DEV_UI 15.3: "a number on
 * every screen and nothing that pops up"). Decisions and unread notices
 * together; the Inbox's own tabs say which.
 *
 * It was a button in the header, wired into the shell -- the third place
 * the frame broke "a sub-app touches the frame only by declaring". The
 * owner chose the rail as its only place (21 October): the rail is
 * present at every width, so the count is still on every screen.
 *
 * Re-read on every navigation, as the header's was: deciding something
 * on a page should not leave a stale number on the rail beside it.
 * Between navigations the counts' own hook polls and listens for live
 * updates (useInboxCounts).
 */
import type { Badge } from '@shell/core/badges'
import { totalWaiting, useInboxCounts } from '@elysium/shell-api/useInboxCounts'
import { useLocation } from 'react-router-dom'

export function useInboxBadges(): Record<string, Badge | undefined> {
  const location = useLocation()
  const waiting = totalWaiting(useInboxCounts(location.pathname + location.search))
  return { '/inbox': { count: waiting, label: `${waiting} waiting` } }
}
