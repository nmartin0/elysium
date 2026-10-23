/**
 * THE INBOX AS A MODULE (BLOCKING.md item 3, step 3): the entry of its
 * own bundle, built apart from Elysium's page by vite.config.ts in this
 * folder. Elysium's page no longer imports it. It was ui/src/inbox and
 * ui/src/InboxPanel.tsx; a modules.yaml naming the old folder is read as
 * naming this one (core/modules.py, MOVED_MODULES).
 *
 * LOADED AS THE FRAME IS DRAWN, not when /inbox is first opened: its
 * manifest names `onStartup`, because its badge -- how much is waiting,
 * on its rail entry -- is on every screen. So the page and the badge
 * come in one bundle at startup; both are small, and the tabs' own code
 * still waits for its modules' bundles (Approvals, Notifications,
 * Identity), each loaded when the Inbox first shows one of theirs.
 *
 * What the page used to hand it as a prop -- what to do when the session
 * ends -- it reads from the kit's host store, as Query and Schema do.
 */
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import { useInboxBadges } from './badges'
import InboxPanel from './InboxPanel'
import './InboxPanel.css'

function InboxPage() {
  const { onSessionExpired } = useHostValues()
  return <InboxPanel onSessionExpired={onSessionExpired} />
}

/** Its page, by the id module.json declares, and its rail badge. */
export function activate(): ModuleActivation {
  return { pages: { inbox: InboxPage }, useBadges: useInboxBadges }
}
