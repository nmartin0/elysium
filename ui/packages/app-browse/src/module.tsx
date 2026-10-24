/**
 * BROWSE AS A MODULE (BLOCKING.md item 3, step 3, the last sub-app
 * moved): the entry of its own bundle, built apart from Elysium's page by
 * vite.config.ts in this folder. Elysium's page no longer imports it, and
 * with it goes the page's last code for a module: its palette commands.
 *
 * TWO WAYS IN, LOADED AS SMALL AS EACH NEEDS:
 *   - THE PALETTE (`onPalette` in module.json): the first time the command
 *     palette opens, on any screen, the shell activates this bundle for
 *     `usePalette`. That code is imported here directly, and it is small.
 *   - ITS PAGES, search and an object's page, are CHUNKS OF THEIR OWN
 *     beside this file, fetched when one is first opened -- so opening
 *     the palette on Query does not fetch all of Browse, as it did not
 *     when the page held it (a chunk of the page's own, then).
 *
 * What the page used to hand the pages as props -- the visible schema,
 * the username, what to do when the session ends -- they read from the
 * kit's host store, as Schema's does (@elysium/shell-api/host).
 */
import { lazy } from 'react'
import { useHostValues } from '@elysium/shell-api/host'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import { useBrowsePalette } from './palette'
import './browse.css'

const ObjectSearchPanel = lazy(() => import('./ObjectSearchPanel'))
const ObjectDetailPanel = lazy(() => import('./ObjectDetailPanel'))

function SearchPage() {
  const { visibleSchema, username, onSessionExpired } = useHostValues()
  return <ObjectSearchPanel visibleSchema={visibleSchema} username={username} onSessionExpired={onSessionExpired} />
}

function ObjectPage() {
  const { visibleSchema, onSessionExpired } = useHostValues()
  return <ObjectDetailPanel visibleSchema={visibleSchema} onSessionExpired={onSessionExpired} />
}

/** Its pages by the ids module.json declares, and its palette commands. */
export function activate(): ModuleActivation {
  return { pages: { search: SearchPage, object: ObjectPage }, usePalette: useBrowsePalette }
}
