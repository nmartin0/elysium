/**
 * ADMIN AS A MODULE (BLOCKING.md item 3, step 3): the entry of its own
 * bundle, built apart from Elysium's page by vite.config.ts in this
 * folder and loaded by the shell when /admin is first opened. Elysium's
 * page no longer imports it.
 *
 * PEOPLE AND ROLES: Users and Roles, offered on manage:users. The
 * server's own views were split out before it moved, to the System
 * sub-app's Server page (ui/src/system/ServerPage.tsx), which stays in
 * the page so it loads in safe mode.
 *
 * What the page used to hand it as a prop -- what to do when the session
 * ends -- it reads from the kit's host store, as Query does.
 */
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import AdminPanel from './AdminPanel'
import './AdminPanel.css'

function AdminPage() {
  const { onSessionExpired } = useHostValues()
  return <AdminPanel onSessionExpired={onSessionExpired} />
}

/** The pages by the ids module.json declares. */
export function activate(): ModuleActivation {
  return { pages: { admin: AdminPage } }
}
