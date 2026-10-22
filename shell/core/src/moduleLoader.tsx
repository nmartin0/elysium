/**
 * Loading a module's code: its bundle, its stylesheets, its lifecycle.
 *
 * WHAT A BUNDLE IS. An ES module, built apart from the page with the
 * shared libraries left as bare imports (@shell/build), exporting:
 *
 *     export function activate(context: ModuleContext): ModuleActivation
 *     export function deactivate(): void          // optional
 *
 * `activate` returns the module's pages by id -- the ids its manifest's
 * `contributes.pages` declares. VS Code's shape: `activate(context)` runs
 * when the extension is first needed and `deactivate` when it is unloaded;
 * single-spa's lifecycle is the same idea with more steps.
 *
 * LAZY. Nothing loads until one of the module's pages is opened: `page()`
 * returns a component at once, and the bundle is fetched when React first
 * renders it. The component is the same object every time it is asked
 * for, so a re-render never remounts a module's page.
 *
 * A MODULE IS ITS ADDRESS. The backend changes a bundle's address whenever
 * its code changes (Elysium adds a fingerprint of the file), because the
 * browser imports an address once per page; a new address is a new
 * module, and the old one is unloaded first.
 *
 * A FAILURE IS A PAGE, NOT A CRASH. A bundle that cannot be fetched, does
 * not export `activate`, or does not offer the page asked for renders a
 * sentence saying which module and why. The rest of the shell is
 * unaffected. The failed page STAYS failed until the feed is next applied
 * (`retain`), so a re-render does not retry -- and remount -- every time;
 * then the next attempt tries again.
 *
 * UNLOADING WHILE LOADING CANCELS. A module unloaded before its import
 * finishes -- a sign-out, a newer version -- is never activated, or if
 * `activate` was already running, is deactivated as soon as it returns:
 * no activation is ever left without its `deactivate`.
 *
 * UNLOADING removes a module's stylesheets and calls its `deactivate`. The
 * browser keeps the module's code until the next page load (BLOCKING.md
 * item 3: an ES module cannot be unloaded), so loading the same version
 * again reuses it.
 */
import { lazy, type ComponentType } from 'react'
import type { ModuleEntry } from './contract'
import type { PaletteHook } from './palette'

/** What a module's `activate` is given. Grows with the frame's requests
 *  (navigation, notices, full screen) in step 1.3. */
export interface ModuleContext {
  id: string
  version: string
}

/** What `activate` returns: the module's pages, by the ids its manifest
 *  declares. */
export interface ModuleActivation {
  pages: Record<string, ComponentType>
  /** Its palette commands, for a module whose manifest names the
   *  `onPalette` activation event (palette.tsx). */
  usePalette?: PaletteHook
}

interface ModuleExports {
  activate?: (context: ModuleContext) => ModuleActivation | Promise<ModuleActivation>
  deactivate?: () => void
}

/** How a bundle is fetched: the browser's own `import()` by default. */
export type Importer = (address: string) => Promise<unknown>

/** The attribute marking a module's stylesheet links, valued by its id. */
export const STYLE_ATTRIBUTE = 'data-shell-module'

export function ModuleLoadFailed({ moduleId, reason }: { moduleId: string; reason: string }) {
  return (
    <div className="shell__module-load-failed" role="alert">
      <p>
        The module <code>{moduleId}</code> could not be loaded: {reason}
      </p>
    </div>
  )
}

interface Loaded {
  entry: string
  activation: Promise<ModuleActivation>
  exports?: ModuleExports
  /** Set by `unload`; a load still in flight stops when it sees it. */
  cancelled: boolean
  /** Set once `activate` has returned and been accepted: only then is
   *  there something for `unload` to deactivate. */
  active: boolean
}

/** A load stopped because its module was unloaded first. */
class Cancelled extends Error {}

export class ModuleLoader {
  private readonly loaded = new Map<string, Loaded>()
  private readonly pages = new Map<string, ComponentType>()
  /** Modules whose last load failed: their pages stay as they are until
   *  the feed is next applied. */
  private readonly failed = new Set<string>()

  constructor(
    private readonly importer: Importer = (address) => import(/* @vite-ignore */ address),
    private readonly doc: Document = document,
  ) {}

  /** The module's activation, loading it the first time. */
  load(module: ModuleEntry): Promise<ModuleActivation> {
    const existing = this.loaded.get(module.id)
    if (existing !== undefined && existing.entry === module.entry) return existing.activation
    if (existing !== undefined) this.unload(module.id)
    if (module.entry === null) return Promise.reject(new Error('it has no bundle; the page supplies its code'))
    const entry = module.entry

    this.addStyles(module)
    const record: Loaded = { entry, activation: Promise.resolve({ pages: {} }), cancelled: false, active: false }
    record.activation = (async () => {
      const exports = (await this.importer(entry)) as ModuleExports
      if (record.cancelled) throw new Cancelled('it was unloaded while loading')
      if (typeof exports?.activate !== 'function') throw new Error('its bundle does not export `activate`')
      record.exports = exports
      const activation = await exports.activate({ id: module.id, version: module.version })
      if (record.cancelled) {
        // UNLOADED WHILE `activate` RAN: pair it with its deactivate now,
        // since `unload` found nothing yet to deactivate.
        safely(() => exports.deactivate?.())
        throw new Cancelled('it was unloaded while loading')
      }
      if (typeof activation?.pages !== 'object' || activation.pages === null) {
        throw new Error('its `activate` did not return `pages`')
      }
      record.active = true
      return activation
    })()
    record.activation.catch(() => {
      // THE RECORD AND STYLESHEETS GO, so a later `load` tries again; the
      // failed PAGE stays until `retain` (see the class docstring).
      if (this.loaded.get(module.id) !== record) return
      this.loaded.delete(module.id)
      this.removeStyles(module.id)
      this.failed.add(module.id)
    })
    this.loaded.set(module.id, record)
    return record.activation
  }

  /**
   * The component for one of a module's pages: the same object on every
   * call for the same module version and page, so React never remounts
   * it on a re-render.
   */
  page(module: ModuleEntry, pageId: string): ComponentType {
    const key = `${module.id}@${module.entry ?? ''}:${pageId}`
    let component = this.pages.get(key)
    if (component === undefined) {
      component = lazy(async () => {
        try {
          const activation = await this.load(module)
          const Page = activation.pages[pageId]
          if (Page === undefined) throw new Error(`it offers no page called ${pageId}`)
          return { default: Page }
        } catch (error) {
          const reason = error instanceof Error ? error.message : String(error)
          return { default: () => <ModuleLoadFailed moduleId={module.id} reason={reason} /> }
        }
      })
      this.pages.set(key, component)
    }
    return component
  }

  /**
   * Applies a feed: unloads every loaded module whose id is not in `ids`,
   * and lets every failed module try again the next time its page opens.
   */
  retain(ids: Iterable<string>): void {
    const keep = new Set(ids)
    for (const id of [...this.loaded.keys()]) if (!keep.has(id)) this.unload(id)
    for (const id of [...this.failed]) {
      this.failed.delete(id)
      this.dropPages(id)
    }
  }

  /** Removes a module's stylesheets and calls its `deactivate`; a load
   *  still in flight is cancelled. */
  unload(id: string): void {
    const record = this.loaded.get(id)
    if (record === undefined) return
    record.cancelled = true
    this.loaded.delete(id)
    this.dropPages(id)
    this.removeStyles(id)
    if (record.active) safely(() => record.exports?.deactivate?.())
  }

  /** Which modules are loaded, for the module manager and for tests. */
  loadedIds(): string[] {
    return [...this.loaded.keys()]
  }

  private dropPages(id: string): void {
    for (const key of [...this.pages.keys()]) if (key.startsWith(`${id}@`)) this.pages.delete(key)
  }

  private removeStyles(id: string): void {
    for (const link of this.doc.querySelectorAll(`link[${STYLE_ATTRIBUTE}]`)) {
      if (link.getAttribute(STYLE_ATTRIBUTE) === id) link.remove()
    }
  }

  private addStyles(module: ModuleEntry): void {
    for (const href of module.styles ?? []) {
      const link = this.doc.createElement('link')
      link.rel = 'stylesheet'
      link.href = href
      link.setAttribute(STYLE_ATTRIBUTE, module.id)
      this.doc.head.appendChild(link)
    }
  }
}

/** A module's own clean-up failing must not stop the shell's. */
function safely(clean: () => void): void {
  try {
    clean()
  } catch {
    // Reported by the module, if at all; the shell carries on.
  }
}
