/**
 * THE BACKEND CONTRACT -- what any server implements so this shell can
 * host its sub-apps. Plain HTTP and JSON; the shell assumes nothing else
 * about the backend. README.md is the same contract written for a person
 * implementing it.
 *
 * VERSION 1, so far: the session and the module feed. Change events and
 * module management (enable, disable, refresh) arrive with the module
 * manager.
 *
 * WHY A FEED. Piral's shell loads whatever its feed service lists -- each
 * micro frontend's `name`, `version` and `link`, with `integrity` and
 * `config` -- and knows nothing else about the server. Native
 * Federation's host takes the same list. A feed is what makes the shell
 * reusable by a backend that is not Elysium.
 *
 * WHY CONTRIBUTIONS ARE DATA. VS Code's `contributes` are "static
 * declarations that you make in the package.json", read without running
 * the extension, so its menus show an entry before its code has loaded.
 * Here the rail and the routes come from the feed, and a module's code
 * loads when one of its pages is first opened.
 */

/** The only contract version this shell speaks. */
export const CONTRACT_VERSION = 1

/** A page a module offers, at a route path the shell mounts. */
export interface PageContribution {
  /** Unique within the module; names the page to the module's code. */
  id: string
  /** A react-router path, e.g. `/schema` or `/objects/:type/:id`. */
  path: string
}

/** An entry in the shell's navigation rail. */
export interface NavContribution {
  title: string
  /** Where it leads: one of the module's own page paths. */
  path: string
  /** The rail groups by what a person is working on, not by module. */
  subject?: string
}

/** An old address that still leads somewhere. */
export interface RedirectContribution {
  from: string
  to: string
}

export interface Contributions {
  pages?: PageContribution[]
  nav?: NavContribution[]
  redirects?: RedirectContribution[]
}

/** One module, as the feed lists it for the signed-in user. */
export interface ModuleEntry {
  id: string
  name: string
  version: string
  contributes: Contributions
  /** Where the module's code is: a bundle's address, or null when the
   *  host supplies the code itself (a module built into the page). The
   *  bundle is an ES module exporting `activate` (module.ts). */
  entry: string | null
  /** Stylesheets the bundle needs, added when it loads and removed when
   *  it unloads. Optional, so a version-1 feed without it still reads. */
  styles?: string[]
}

/** GET {base}/modules */
export interface ModuleFeed {
  contract: number
  /** Where a signed-in person lands, and where an unknown path leads. */
  home: string
  modules: ModuleEntry[]
}

/** GET {base}/session */
export interface Session {
  /** Null when nobody is signed in -- an answer, not an error. */
  user: { id: string; name: string } | null
  /** How to sign in. `form`: a username and password POSTed as JSON to
   *  `submit`. Other kinds (a redirect to an identity provider) later. */
  sign_in: { kind: 'form'; submit: string }
}

/** Why a feed cannot be used, in words a person can act on. */
export class FeedError extends Error {}

/**
 * Checks a feed's shape before anything is built from it. A backend
 * speaking another contract version is refused by name rather than
 * half-read: a field renamed between versions would otherwise be
 * silently absent.
 */
export function checkFeed(raw: unknown): ModuleFeed {
  if (typeof raw !== 'object' || raw === null) throw new FeedError('the module feed is not an object')
  const feed = raw as Partial<ModuleFeed>
  if (feed.contract !== CONTRACT_VERSION) {
    throw new FeedError(`the backend speaks contract ${String(feed.contract)}; this shell speaks ${CONTRACT_VERSION}`)
  }
  if (typeof feed.home !== 'string' || !Array.isArray(feed.modules)) {
    throw new FeedError('the module feed needs `home` and `modules`')
  }
  const seen = new Set<string>()
  for (const module of feed.modules) {
    if (typeof module?.id !== 'string' || module.id === '') throw new FeedError('a module in the feed has no id')
    if (seen.has(module.id)) throw new FeedError(`two modules in the feed are called ${module.id}`)
    seen.add(module.id)
    if (module.entry !== null && typeof module.entry !== 'string') {
      throw new FeedError(`${module.id}: \`entry\` must be an address or null`)
    }
    if (
      module.styles !== undefined &&
      !(Array.isArray(module.styles) && module.styles.every((s) => typeof s === 'string'))
    ) {
      throw new FeedError(`${module.id}: \`styles\` must be a list of addresses`)
    }
  }
  return feed as ModuleFeed
}

/** Reads the feed from a backend's contract base, e.g. `/api/shell`. */
export async function fetchFeed(base: string, init?: RequestInit): Promise<ModuleFeed> {
  const response = await fetch(`${base}/modules`, { credentials: 'same-origin', ...init })
  if (!response.ok) throw new FeedError(`the module feed answered ${response.status}`)
  return checkFeed(await response.json())
}
