/**
 * THE SCHEMA GRAPH AS A MODULE (BLOCKING.md item 3, step 1.2): the entry
 * of its own bundle, built apart from Elysium's page by vite.config.ts in
 * this folder and loaded by the shell when /schema is first opened.
 *
 * Elysium's page no longer imports the Schema graph. What the page used
 * to hand it as props -- the visible schema, the username, what to do
 * when the session ends -- it now reads from the kit's host store, which
 * the page publishes into (@elysium/shell-api/host).
 */
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import SchemaPanel from './SchemaPanel'

function SchemaPage() {
  const { visibleSchema, username, onSessionExpired } = useHostValues()
  return <SchemaPanel visibleSchema={visibleSchema} username={username} onSessionExpired={onSessionExpired} />
}

/** The pages by the ids module.json declares. */
export function activate(): ModuleActivation {
  return { pages: { schema: SchemaPage } }
}
