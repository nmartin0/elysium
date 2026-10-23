/**
 * THE NOTIFICATIONS TAB AS A MODULE (BLOCKING.md item 3, step 3): the entry
 * of its own bundle, built apart from Elysium's page by vite.config.ts in
 * this folder and loaded by the shell when the Inbox first shows its tab.
 * Elysium's page no longer imports it.
 *
 * NO PAGES OF ITS OWN: one tab in the Inbox's slot (module.json's `into`),
 * drawn by the Inbox with the slot's context -- how to end the session --
 * as props.
 */
import type { ModuleActivation } from '@shell/core/moduleLoader'
import NotificationsPanel from './NotificationsPanel'
import './NotificationsPanel.css'

/** Its contributions by the ids module.json declares. */
export function activate(): ModuleActivation {
  return { pages: {}, contributions: { notifications: NotificationsPanel } }
}
