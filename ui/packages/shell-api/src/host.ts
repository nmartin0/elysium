/**
 * What a sub-app's pages need from Elysium's page: the schema this
 * person may see, who they are, and what to do when their session ends.
 *
 * BLOCKING.md item 3, step 1.2. Before modules, `App.tsx` handed these to
 * each page as props. A module built apart from the page cannot be handed
 * props by code that does not know it exists, so Elysium's page PUBLISHES
 * them here and a page reads them with a hook. This works across separate
 * bundles because the kit is shared as ONE instance (ui/src/
 * sharedLibraries.ts): the module's `@elysium/shell-api` is the page's.
 *
 * ELYSIUM'S, NOT THE SHELL'S. The generic shell knows nothing of schemas;
 * this belongs to Elysium's API package, beside the client that fetches
 * them.
 *
 * A store rather than a React context, because a module's pages are
 * mounted by the shell's routes and owe nothing to where the page's
 * providers sit; `useSyncExternalStore` keeps every reader in step with
 * the last publish.
 */
import { useSyncExternalStore } from 'react'
import type { VisibleSchema } from './types'

export interface HostValues {
  /** The object types and fields this person may see; null until fetched. */
  visibleSchema: VisibleSchema | null
  /** Who is signed in; '' until known. */
  username: string
  /** Ends the session in the page: the sign-in form comes back. */
  onSessionExpired: () => void
}

const INITIAL: HostValues = { visibleSchema: null, username: '', onSessionExpired: () => {} }

let current: HostValues = INITIAL
const listeners = new Set<() => void>()

/** Called by Elysium's page whenever any of these changes. */
export function publishHostValues(values: HostValues): void {
  current = values
  for (const listener of listeners) listener()
}

/**
 * SETS the values without telling anyone: for the page to call DURING
 * ITS OWN RENDER, so a module's page rendering beneath it in the same
 * pass already reads them. Publishing (telling the readers) waits for
 * the page's layout effect, since updating other components mid-render
 * is forbidden. Without this, a module page mounting with the page saw
 * empty values in its first render and ran its first effects with them.
 * Idempotent: a render React discards stages what the next one stages
 * again.
 */
export function stageHostValues(values: HostValues): void {
  current = values
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

/** Everything the page has published, re-rendering when it changes. */
export function useHostValues(): HostValues {
  return useSyncExternalStore(subscribe, () => current)
}

/** For tests: back to nothing published. */
export function resetHostValues(): void {
  publishHostValues(INITIAL)
}
