/**
 * QUERY AS A MODULE (BLOCKING.md item 3, step 3): the entry of its own
 * bundle, built apart from Elysium's page by vite.config.ts in this
 * folder and loaded by the shell when /query is first opened. Elysium's
 * page no longer imports it.
 *
 * /query IS WHERE A PERSON LANDS after logging in (modules.yaml's
 * `home`), so on most deployments this bundle is asked for straight after
 * login -- the page is smaller for everyone who lands elsewhere, and the
 * same size as before for everyone who lands here.
 *
 * What the page used to hand it as a prop -- what to do when the session
 * ends -- it reads from the kit's host store, as Schema does
 * (@elysium/shell-api/host).
 */
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import QueryPanel from './QueryPanel'
import './QueryPanel.css'

function QueryPage() {
  const { onSessionExpired } = useHostValues()
  return <QueryPanel onSessionExpired={onSessionExpired} />
}

/** The pages by the ids module.json declares. */
export function activate(): ModuleActivation {
  return { pages: { query: QueryPage } }
}
