/**
 * The Inbox: approvals, notifications, merge proposals, enrichment
 * rules, predicted fields and unusual values, one place
 * (DEV_UI 12, 15; decided by the owner 14 Oct).
 *
 * "INBOXES. Approvals and notifications are about EVENTS THAT ARRIVED,
 * not something being explored." They were three rail entries, which is
 * the by-feature decomposition 12 names -- three tools for one kind of
 * thing. They are three TABS now, each the panel it always was, so
 * nothing about deciding a write or a merge changed; only where it
 * lives.
 *
 * THE TAB IS IN THE URL (`?tab=`), so a link to a tab is a link, and the
 * old paths -- /approvals, /notifications, /identity -- land on theirs.
 *
 * EACH TAB SAYS HOW MUCH IS WAITING IN IT, from the same counts as the
 * Inbox's rail badge, so the reader goes to the tab where the work is
 * rather than opening each to find out.
 */

import { Suspense } from 'react'
import { Tab, Tabs } from '@blueprintjs/core'
import type { IconName } from '@blueprintjs/core'
import { useLocation } from 'react-router-dom'
import { useSlot } from '@shell/core/slots'

import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useInboxCounts } from '@elysium/shell-api/useInboxCounts'
import { useUrlValue } from '@elysium/shell-api/useUrlState'

/**
 * THE INBOX'S TABS ARE A SLOT (step 1.5b), `inbox.tabs`: Approvals,
 * Notifications and Identity are modules of their own and contribute
 * them -- this file no longer imports any of them. The order is the
 * Inbox's own (module.json, the owner's choice), so it reads as it
 * always has; a tab from a module it does not list follows. A module the
 * person is not offered, or one turned off, simply has no tab here.
 *
 * What each tab is given: `onSessionExpired`, the slot's whole context.
 */
interface InboxTabProps {
  onSessionExpired: () => void
}

export default function InboxPanel({ onSessionExpired }: { onSessionExpired: () => void }) {
  const tabs = useSlot<InboxTabProps>('inbox.tabs')
  const [requested, setTab] = useUrlValue('tab', tabs[0]?.id ?? 'approvals')
  const tab = tabs.some((t) => t.id === requested) ? requested : (tabs[0]?.id ?? requested)
  const location = useLocation()
  const counts = useInboxCounts(location.search) as Record<string, number | undefined> | null

  return (
    <div className="inbox">
      <Tabs id="inbox" selectedTabId={tab} onChange={(next) => setTab(String(next))} renderActiveTabPanelOnly large>
        {tabs.map(({ id, title, icon, Component }) => {
          const waiting = counts?.[id] ?? 0
          return (
            <Tab
              key={id}
              id={id}
              title={title}
              icon={icon as IconName | undefined}
              tagContent={waiting > 0 ? waiting : undefined}
              tagProps={{ round: true, intent: id === 'notifications' ? 'none' : 'warning' }}
              panel={
                <Suspense fallback={<LoadingState />}>
                  <Component onSessionExpired={onSessionExpired} />
                </Suspense>
              }
            />
          )
        })}
      </Tabs>
    </div>
  )
}
