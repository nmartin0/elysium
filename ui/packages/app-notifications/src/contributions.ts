/** WHAT THE NOTIFICATIONS MODULE PUTS IN OTHER MODULES' SLOTS (step 1.5b):
 *  the Inbox's Notifications tab, loaded when it is first opened. Its
 *  icon (module.json) is a BELL, not an envelope: this is what the
 *  deployment told you, not mail somebody sent. */
import { lazy } from 'react'

export const contributions = {
  notifications: lazy(() => import('./NotificationsPanel')),
}
