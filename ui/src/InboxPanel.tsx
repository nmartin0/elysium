/**
 * The Inbox: approvals, notifications and merge proposals, one place
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
 * header's badge, so the reader goes to the tab where the work is
 * rather than opening each to find out.
 */

import { lazy, Suspense } from 'react'
import { Tab, Tabs } from '@blueprintjs/core'
import type { IconName } from '@blueprintjs/core'
import { useLocation } from 'react-router-dom'

import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useInboxCounts } from '@elysium/shell-api/useInboxCounts'
import { useUrlValue } from '@elysium/shell-api/useUrlState'

const ApprovalsPanel = lazy(() => import('@elysium/app-approvals/ApprovalsPanel'))
const NotificationsPanel = lazy(() => import('@elysium/app-notifications/NotificationsPanel'))
const IdentityPanel = lazy(() => import('@elysium/app-identity/IdentityPanel'))

export type InboxTab = 'approvals' | 'notifications' | 'identity'

const TABS: readonly { id: InboxTab; title: string; icon: IconName }[] = [
  { id: 'approvals', title: 'Approvals', icon: 'inbox' },
  // A BELL, not an envelope: this is what the deployment told you, not
  // mail somebody sent.
  { id: 'notifications', title: 'Notifications', icon: 'notifications' },
  // merge-columns: the tab is about deciding whether two records are
  // ONE. A padlock would say "security" and mislead.
  { id: 'identity', title: 'Identity', icon: 'merge-columns' },
]

function isTab(value: string): value is InboxTab {
  return TABS.some((tab) => tab.id === value)
}

export default function InboxPanel({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [requested, setTab] = useUrlValue('tab', 'approvals')
  const tab: InboxTab = isTab(requested) ? requested : 'approvals'
  const location = useLocation()
  const counts = useInboxCounts(location.search)

  return (
    <div className="inbox">
      <Tabs id="inbox" selectedTabId={tab} onChange={(next) => setTab(String(next))} renderActiveTabPanelOnly large>
        {TABS.map(({ id, title, icon }) => {
          const waiting = counts?.[id] ?? 0
          return (
            <Tab
              key={id}
              id={id}
              title={title}
              icon={icon}
              tagContent={waiting > 0 ? waiting : undefined}
              tagProps={{ round: true, intent: id === 'notifications' ? 'none' : 'warning' }}
              panel={
                <Suspense fallback={<LoadingState />}>
                  {id === 'approvals' && <ApprovalsPanel onSessionExpired={onSessionExpired} />}
                  {id === 'notifications' && <NotificationsPanel onSessionExpired={onSessionExpired} />}
                  {id === 'identity' && <IdentityPanel onSessionExpired={onSessionExpired} />}
                </Suspense>
              }
            />
          )
        })}
      </Tabs>
    </div>
  )
}
