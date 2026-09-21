import type React from 'react'
/**
 * NotificationsPanel -- what the deployment has told this person.
 *
 * WHY IT EXISTS SEPARATELY FROM APPROVALS. An approval is something
 * only you can act on and somebody is waiting for. A notification is
 * something you should know, and often nobody is waiting. Mixing them
 * makes the queue that needs action indistinguishable from the one
 * that needs reading.
 *
 * EVERYTHING HERE IS THIS PERSON'S OWN. The server scopes by user in
 * the query -- there is no call that returns anybody else's -- so
 * this panel has no filtering to get wrong.
 *
 * MARKED SEEN ON A CLICK, NOT ON RENDER. Opening a list is not
 * reading it, and a badge that cleared itself the moment somebody
 * glanced at the tab would lose the one thing it is for.
 */

import { Button, Callout, Card, CardList, NonIdealState, Tab, Tabs, Tag } from '@blueprintjs/core'
import {
  getErrorMessage,
  getNotifications,
  handleIfSessionExpired,
  markNotificationSeen,
  type Notification,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useCallback, useEffect, useState } from 'react'

import WatchList from './WatchList'

interface NotificationsPanelProps {
  onSessionExpired: () => void
}

/** A word for each kind, because the kind itself is a database value. */
const KIND_LABELS: Record<string, string> = {
  mirror_health: 'Mirror',
  count_condition: 'Watch',
  count_condition_watching: 'Watch',
}

export default function NotificationsPanel({ onSessionExpired }: NotificationsPanelProps) {
  const [notifications, setNotifications] = useState<Notification[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setNotifications((await getNotifications()).notifications)
      setError(null)
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }, [onSessionExpired])

  useEffect(() => {
    void load()
  }, [load])

  async function handleSeen(notificationId: string) {
    try {
      await markNotificationSeen(notificationId)
      // RE-READ RATHER THAN PATCH IN PLACE. The server decides what
      // is seen, and a local edit that disagreed with it would show
      // one thing here and another after a reload.
      await load()
    } catch (caught: unknown) {
      if (handleIfSessionExpired(caught, onSessionExpired)) return
      setError(getErrorMessage(caught))
    }
  }

  // TWO ENDS OF ONE QUESTION: what have I been told, and what will
  // tell me. Somebody silencing a noisy trigger arrives here from the
  // notice it sent, and a separate screen would make them go looking.
  const withTabs = (inbox: React.ReactNode) => (
    <Tabs id="notifications" defaultSelectedTabId="inbox">
      <Tab id="inbox" title="Notifications" panel={<>{inbox}</>} />
      <Tab id="watching" title="Watching" panel={<WatchList onSessionExpired={onSessionExpired} />} />
    </Tabs>
  )

  if (error !== null) return withTabs(<ErrorState>{error}</ErrorState>)
  if (notifications === null) return withTabs(<LoadingState />)

  if (notifications.length === 0) {
    return withTabs(
      <NonIdealState
        icon="notifications"
        title="Nothing to report"
        description="Conditions you are watching will appear here when they change."
      />,
    )
  }

  return withTabs(
    <div className="notifications">
      <CardList>
        {notifications.map((notification) => (
          <Card key={notification.notification_id} className="notifications__item">
            <div className="notifications__head">
              <Tag minimal intent={notification.seen ? 'none' : 'primary'}>
                {KIND_LABELS[notification.kind] ?? notification.kind}
              </Tag>
              <span className="notifications__when">{formatTimestamp(notification.created_at)}</span>
              {!notification.seen && (
                <Button minimal small onClick={() => void handleSeen(notification.notification_id)}>
                  Mark as read
                </Button>
              )}
            </div>
            <p className="notifications__summary">{notification.summary}</p>
            {notification.detail !== null && <Callout className="notifications__detail">{notification.detail}</Callout>}
          </Card>
        ))}
      </CardList>
    </div>,
  )
}
