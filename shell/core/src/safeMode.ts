/**
 * SAFE MODE (BLOCKING.md item 3, step 1.4b): the page loaded with only
 * the PINNED modules -- the system's own sub-apps -- for when a module
 * breaks it.
 *
 * Firefox's Troubleshoot Mode is the precedent: it disables add-ons, is
 * entered from a menu or by holding Shift, and "these changes are
 * temporary". So here:
 *
 * THIS BROWSER TAB, AND TEMPORARY. Nothing on the server changes; the
 * switch lives in the tab's session storage, so it holds across the
 * page's own navigation and reloads and ends when the tab closes. Other
 * people, and this person's other tabs, are untouched.
 *
 * ENTERING AND LEAVING RELOAD THE PAGE. A browser keeps a module's
 * imported code until the page reloads (the loader's `unload` removes
 * its pages and styles, not its code), so a module that broke the page
 * could still be running in it. A fresh load is the only clean state --
 * Firefox restarts for the same reason.
 *
 * AN ADDRESS ANYONE CAN TYPE: `/?safe`. When a module breaks the page
 * badly enough that no menu can be reached, the address bar still can.
 * The marker is taken out of the address once read, so a bookmark or a
 * shared link made in safe mode does not carry it.
 */
import type { ModuleFeed } from './contract'

const KEY = 'shell.safeMode'
const PARAMETER = 'safe'

/** The pieces of `window` safe mode uses, so tests can supply their own. */
export interface SafeModeHost {
  location: Pick<Location, 'search' | 'pathname' | 'hash' | 'assign'>
  history: Pick<History, 'replaceState' | 'state'>
  storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'> | null
}

function browser(): SafeModeHost {
  let storage: Storage | null = null
  try {
    storage = window.sessionStorage
  } catch {
    // Storage refused: safe mode still works for this one load, by address.
  }
  return { location: window.location, history: window.history, storage }
}

/**
 * Whether this page load is in safe mode: asked by `/?safe`, or carried
 * on from an earlier load in this tab. Read ONCE, at load; the answer
 * cannot change without a reload.
 */
export function safeModeAtLoad(host: SafeModeHost = browser()): boolean {
  const query = new URLSearchParams(host.location.search)
  if (query.has(PARAMETER)) {
    try {
      host.storage?.setItem(KEY, '1')
    } catch {
      // As above: this load is safe whether or not the next one remembers.
    }
    query.delete(PARAMETER)
    const rest = query.toString()
    host.history.replaceState(host.history.state, '', `${host.location.pathname}${rest ? `?${rest}` : ''}${host.location.hash}`)
    return true
  }
  try {
    return host.storage?.getItem(KEY) === '1'
  } catch {
    return false
  }
}

/** Reloads the page in safe mode, at home. */
export function enterSafeMode(host: SafeModeHost = browser()): void {
  host.location.assign(`/?${PARAMETER}`)
}

/** Reloads the page with every module, at home. */
export function leaveSafeMode(host: SafeModeHost = browser()): void {
  try {
    host.storage?.removeItem(KEY)
  } catch {
    // Nothing remembered to forget.
  }
  host.location.assign('/')
}

/**
 * The feed as safe mode loads it: only the pinned modules. Home stays
 * where it is if a pinned module's page is there, and otherwise moves to
 * the first pinned module's first page -- or stays, opening nothing, for
 * someone offered no pinned module, who then sees the frame and the way
 * out of safe mode.
 */
export function safeFeed(feed: ModuleFeed): ModuleFeed {
  const pinned = feed.modules.filter((module) => module.pinned === true)
  const paths = pinned.flatMap((module) => (module.contributes.pages ?? []).map((page) => page.path))
  return { ...feed, modules: pinned, home: paths.includes(feed.home) ? feed.home : (paths[0] ?? feed.home) }
}

/** The address that opens safe mode, for links in failure messages. */
export const SAFE_MODE_ADDRESS = `/?${PARAMETER}`
