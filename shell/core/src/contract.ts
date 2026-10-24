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

/**
 * THE MODULE API THIS PAGE OFFERS (BLOCKING.md item 3, step 4): one
 * version for everything a module may rely on -- the kit's and the
 * shell's names in ui/module-api.report.md, the manifest, what
 * `activate` returns, the host values, the tokens and the add-on
 * contract. MAJOR.MINOR: an addition raises the minor, a change or a
 * removal the major. Not the feed's CONTRACT_VERSION, which is what the
 * BACKEND speaks to the shell; this is what the page offers its modules.
 *
 * A MODULE SAYS WHICH IT NEEDS, in module.json's `api`: "^1.0" is 1.0 or
 * any later 1.x -- VS Code's `engines.vscode`, "the versions of VS Code
 * that the extension is compatible with", where "^0.10.5 indicates
 * compatibility with a minimum VS Code version of 0.10.5".
 */
export const MODULE_API_VERSION = '1.0'

/** "^1.0", and only that form: a caret, a major, a minor. */
const API_RANGE = /^\^(0|[1-9]\d*)\.(0|[1-9]\d*)$/

/**
 * Why this page cannot load `module`, or null when it can: the module
 * names no API version, names one in a form not understood, or needs one
 * this page does not offer. Said so a person can act on it, in the
 * module manager, which lists the module with this beside it.
 */
export function apiRefusal(module: Pick<ModuleEntry, 'api'>, offered: string = MODULE_API_VERSION): string | null {
  if (module.api === undefined) return 'it names no module API version: its module.json needs `"api": "^1.0"`'
  const wanted = API_RANGE.exec(module.api)
  if (wanted === null) return `its module.json's \`api\` is "${module.api}", not a version such as "^1.0"`
  const [major, minor] = offered.split('.').map(Number) as [number, number]
  const [needMajor, needMinor] = [Number(wanted[1]), Number(wanted[2])]
  if (needMajor === major && needMinor <= minor) return null
  return `it needs the module API ${module.api}, and this page offers ${offered}`
}

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

/**
 * A PLACE A MODULE'S PAGE OFFERS TO OTHERS (step 1.5) -- Backstage's
 * extension "input", Grafana's "extension point". The owner draws it,
 * with `useSlot(id)` (slots.tsx); `order` lists the contribution ids it
 * wants first, in that order, and any it does not list follow in feed
 * order.
 */
export interface SlotDeclaration {
  id: string
  order?: string[]
}

/**
 * A MODULE'S CONTRIBUTION TO ANOTHER'S SLOT, declared STATICALLY so the
 * shell knows of it without loading any code -- Grafana's rule that
 * "you must update your plugin.json metadata to list any registered
 * extensions". The component comes from the module's code
 * (`activate` -> `contributions[id]`) when the slot first shows it.
 */
export interface SlotContribution {
  slot: string
  /** Unique within the module; names the component in its code. */
  id: string
  title: string
  /** A Blueprint icon name, for owners that draw one (a tab's). */
  icon?: string
}

export interface Contributions {
  pages?: PageContribution[]
  nav?: NavContribution[]
  redirects?: RedirectContribution[]
  slots?: SlotDeclaration[]
  into?: SlotContribution[]
}

/** One module, as the feed lists it for the signed-in user. */
/**
 * WHEN A MODULE'S CODE RUNS besides a page of it being opened -- VS Code's
 * `activationEvents`, where an extension is "activated lazily" and says
 * on which events. `onPalette`: when the command palette opens, so the
 * commands its code supplies are there although none of its pages has
 * been opened yet. `onStartup`: when the frame is drawn, so a badge on
 * its rail entry is on every screen (activation.ts).
 *
 * A FEED MAY NAME ONE THIS SHELL DOES NOT KNOW (a newer backend), and it
 * is ignored rather than refused: the module still loads when its page
 * opens, which is what a shell without the event would have done anyway.
 */
export const ACTIVATION_EVENTS = ['onPalette', 'onStartup'] as const
export type ActivationEvent = (typeof ACTIVATION_EVENTS)[number]

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
  /** When its code runs besides its pages opening. Optional: a feed
   *  without it activates modules only by their pages. */
  activationEvents?: string[]
  /** The module API it needs, as module.json says: "^1.0" (see
   *  MODULE_API_VERSION). Optional in the feed, so a backend that
   *  predates it still reads -- and a module without one is not loaded
   *  (apiRefusal), and says why. */
  api?: string
  /**
   * A SYSTEM SUB-APP (step 1.4): loaded in safe mode, and nothing in the
   * interface turns it off -- safe mode exists for when a module breaks
   * the page, and a module must not be able to take away the tool that
   * fixes it. The backend decides which; a module cannot pin itself.
   */
  pinned?: boolean
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
    if (
      module.activationEvents !== undefined &&
      !(Array.isArray(module.activationEvents) && module.activationEvents.every((e) => typeof e === 'string'))
    ) {
      throw new FeedError(`${module.id}: \`activationEvents\` must be a list of event names`)
    }
    if (module.api !== undefined && typeof module.api !== 'string') {
      throw new FeedError(`${module.id}: \`api\` must be a version such as "^1.0"`)
    }
    if (module.pinned !== undefined && typeof module.pinned !== 'boolean') {
      throw new FeedError(`${module.id}: \`pinned\` must be true or false`)
    }
  }
  return feed as ModuleFeed
}

/**
 * The feed as this page can load it: only the modules whose API it
 * offers (apiRefusal). Home moves as safe mode moves it (safeFeed), to
 * the first page left, if its own module is the one left out.
 */
export function compatibleFeed(feed: ModuleFeed, offered: string = MODULE_API_VERSION): ModuleFeed {
  const modules = feed.modules.filter((module) => apiRefusal(module, offered) === null)
  if (modules.length === feed.modules.length) return feed
  const paths = modules.flatMap((module) => (module.contributes.pages ?? []).map((page) => page.path))
  return { ...feed, modules, home: paths.includes(feed.home) ? feed.home : (paths[0] ?? feed.home) }
}

/** Reads the feed from a backend's contract base, e.g. `/api/shell`. */
export async function fetchFeed(base: string, init?: RequestInit): Promise<ModuleFeed> {
  const response = await fetch(`${base}/modules`, { credentials: 'same-origin', ...init })
  if (!response.ok) throw new FeedError(`the module feed answered ${response.status}`)
  return checkFeed(await response.json())
}

/** Whether a module asked to be activated on `event`. */
export function activatesOn(module: ModuleEntry, event: ActivationEvent): boolean {
  return module.activationEvents?.includes(event) ?? false
}

/**
 * WHAT THE MODULE MANAGER ARRANGES (step 1.4c): `GET {base}/modules/
 * arrangement`, and `PUT` the same with the new order -- every module the
 * deployment knows, on and off, for whoever may manage it. Pinned ones are
 * listed, and never arranged: always on, always last.
 */
export interface ArrangedModule {
  id: string
  name: string
  version: string
  enabled: boolean
  pinned: boolean
  /** Its pages' paths, for choosing home. */
  pages: string[]
}

export interface ModuleArrangement {
  home: string
  modules: ArrangedModule[]
  /** Of the arrangement as read: a save names it, and the backend refuses
   *  one made against an arrangement that has since changed. */
  digest: string
}

/** A new arrangement: every arrangeable module, by id, on or off, in rail
 *  order -- pinned ones left out. */
export interface ModuleArrangementChange {
  home: string
  modules: [string, boolean][]
  digest: string
}
