/**
 * THE FRAME: the rail, the header and the command palette around every
 * page (BLOCKING.md item 3, "THE FRAME AND THE SUB-APP", step 1.3).
 *
 * The shell owns the frame; a sub-app owns everything inside the content
 * area. GENERIC: the host supplies what is its own -- the product's name,
 * the header's actions (a user menu, help, a theme switch), its commands,
 * the icon for each rail entry, what shows while a page loads -- and the
 * frame draws them. Moved here from Elysium's `ui/src/Shell.tsx`, which
 * is now the host's composition of it.
 *
 * STYLED BY THE HOST, for now: the frame renders stable class names
 * (`app-frame`, `app__header`, `app__sidebar`, `app__nav`...) and the
 * host's stylesheet draws them -- Elysium's in its kit's index.css. The
 * look as a baseline every sub-app inherits (tokens, then the kit) is
 * its own later step; until then the class names are the frame's
 * styling contract and are kept exactly as they were.
 *
 * Rendered as a react-router LAYOUT route: pages mount in its <Outlet />.
 */
import { Classes, Icon, Menu, MenuItem, type IconName, type MaybeElement } from '@blueprintjs/core'
import { Suspense, useEffect, useMemo, useRef, useState, useSyncExternalStore, type ReactNode } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import CommandPalette from './CommandPalette'
import { type Command, mayFireGlobally, opensPalette } from './commands'
import { useActivated, type FrameModules } from './activation'
import { BadgeSource, badgeText, useBadgeReports, type Badge } from './badges'
import { PaletteSource, useContributions } from './palette'

/** One entry on the rail: a feed's `nav` contribution. */
export interface FrameNavEntry {
  title: string
  path: string
  /**
   * WHAT A PERSON IS WORKING ON. The rail groups by this rather than
   * listing modules: listing them is "a decomposition BY FEATURE, the way
   * software gets built, not BY WHAT THE USER IS WORKING ON" (Elysium's
   * DEV_UI.md 12). An entry with none gets no heading, so a feed without
   * subjects gives the flat list it always did.
   */
  subject?: string
}

export interface FrameProps {
  /** The rail, in order; entries arrive grouped by subject. */
  nav: readonly FrameNavEntry[]
  /** The product's name, in the header. */
  brand: ReactNode
  /** The header's actions, drawn at its end. */
  actions?: ReactNode
  /** Dialogs and other overlays the host keeps open beside the frame. */
  overlays?: ReactNode
  /** The icon for a rail entry. */
  iconFor: (path: string) => IconName | MaybeElement
  /**
   * The host's palette commands: `before` the frame's own navigation
   * commands (what acts on the page in front of you) and `after` them.
   */
  commands?: { before?: Command[]; after?: Command[] }
  /** Commands made FROM what was typed, listed after every match. */
  suggest?: (query: string) => Command[]
  /**
   * The feed's modules and how the host activates one (activation.ts).
   * The frame activates them on the events their manifests name and
   * reads their code: palette commands (palette.tsx), which sit inside
   * the host's own -- modules' `before`, the host's `before`, navigation,
   * modules' `after`, the host's `after` -- and badges on their own rail
   * entries (badges.tsx).
   */
  modules?: FrameModules
  /** Told each time the palette opens, so a host can load what it lists. */
  onPaletteOpen?: () => void
  /** What the content area shows while a page's code loads. */
  fallback: ReactNode
  /** Where the rail's collapsed state is remembered, per browser. */
  storageKey: string
  /** Set when the page is in safe mode (safeMode.ts): the frame says so
   *  above every page, with the way out. */
  safeMode?: { onLeave: () => void }
  /** Rail entries this person has hidden (RailTabsDialog), by path: left
   *  off the rail, still offered by the palette. */
  hiddenPaths?: ReadonlySet<string>
}

/**
 * The width below which three columns stop fitting and the rail
 * auto-collapses. 1099px MATCHES the host's CSS that makes an expanded
 * rail overlay rather than push; they once disagreed (640 against 1100),
 * and between the two an expanded rail floated over the content with
 * nothing to collapse it. One number, so both change together.
 */
const MOBILE_BREAKPOINT_QUERY = '(max-width: 1099px)'

/**
 * The remembered choice, or the viewport's default when there is none.
 * Called at mount AND again on leaving the narrow width, which is why it
 * is not "initial" anything: the same rule restores a desktop preference
 * the narrow width overrode without storing.
 */
function resolveCollapsed(storageKey: string): boolean {
  try {
    const stored = window.localStorage.getItem(storageKey)
    if (stored !== null) return stored === 'true'
  } catch {
    // Storage refused (private browsing, a full quota): fall through to
    // the viewport, never fail to draw the rail over it.
  }
  return window.matchMedia(MOBILE_BREAKPOINT_QUERY).matches
}

function persistCollapsed(storageKey: string, value: boolean): void {
  try {
    window.localStorage.setItem(storageKey, String(value))
  } catch {
    // A failed write must not break the click: the state still changes,
    // it is just not remembered next visit.
  }
}

// Module-level, so their identity is stable: useSyncExternalStore
// resubscribes whenever `subscribe` changes, and an inline function
// would create and tear down a MediaQueryList on every render.
function subscribeToBreakpoint(onChange: () => void): () => void {
  const list = window.matchMedia(MOBILE_BREAKPOINT_QUERY)
  list.addEventListener('change', onChange)
  return () => list.removeEventListener('change', onChange)
}

function isNarrowNow(): boolean {
  return window.matchMedia(MOBILE_BREAKPOINT_QUERY).matches
}

export function Frame({
  nav,
  brand,
  actions,
  overlays,
  iconFor,
  commands,
  suggest,
  modules,
  onPaletteOpen,
  fallback,
  storageKey,
  safeMode,
  hiddenPaths,
}: FrameProps) {
  const [collapsed, setCollapsed] = useState(() => resolveCollapsed(storageKey))
  const isMobile = useSyncExternalStore(subscribeToBreakpoint, isNarrowNow)
  const location = useLocation()
  const navigate = useNavigate()

  /**
   * THE PALETTE LIVES IN THE FRAME, which is what makes it available
   * everywhere -- Superhuman's guidance, quoted in Elysium's DEV_UI 10.1:
   * one that works on four screens out of seven is one people stop
   * reaching for.
   */
  const [paletteOpen, setPaletteOpen] = useState(false)
  const latestOnPaletteOpen = useRef(onPaletteOpen)
  useEffect(() => {
    latestOnPaletteOpen.current = onPaletteOpen
  })
  useEffect(() => {
    if (paletteOpen) latestOnPaletteOpen.current?.()
  }, [paletteOpen])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // "Never fire a global shortcut while the person is typing" --
      // asked of the registry, which answers yes for a modifier-qualified
      // binding inside a field: a palette that will not open from the
      // box a page focuses on arrival is one people stop reaching for.
      if (!mayFireGlobally(event, event.target)) return
      if (!opensPalette(event)) return
      event.preventDefault()
      setPaletteOpen(true)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  /** Every rail entry is a place to go, grouped as the rail is. The feed
   *  is already filtered per caller, so none is unavailable. */
  const navigationCommands = useMemo(
    () =>
      nav.map((entry) => ({
        id: `go:${entry.path}`,
        label: entry.title,
        group: entry.subject ?? 'Go to',
        run: () => void navigate(entry.path),
      })),
    [nav, navigate],
  )
  const sources = useActivated(modules, 'onPalette', paletteOpen).flatMap(({ module, code }) =>
    code.usePalette ? [{ id: module.id, usePalette: code.usePalette }] : [],
  )
  const [contributions, report] = useContributions()
  // In the feed's order, not the order their answers arrived in.
  const offered = sources.flatMap(({ id }) => contributions.get(id) ?? [])
  const allCommands: Command[] = [
    ...offered.flatMap((c) => c.before ?? []),
    ...(commands?.before ?? []),
    ...navigationCommands,
    ...offered.flatMap((c) => c.after ?? []),
    ...(commands?.after ?? []),
  ]
  const allSuggestions = (query: string) => [
    ...offered.flatMap((c) => c.suggest?.(query) ?? []),
    ...(suggest?.(query) ?? []),
  ]

  /**
   * THE FUNCTIONAL UPDATER IS THE FIX FOR A SHIPPED BUG: this read
   * `!collapsed` from the render's closure, and the Ctrl+B listener
   * (registered once) held the FIRST render's closure for ever -- three
   * presses gave true, false, false, false. The updater sees the latest
   * queued state whichever closure calls it; the write happens inside it
   * because only there is the resolved value known. Writing the same
   * value twice under Strict Mode is harmless.
   */
  function toggleCollapsed() {
    setCollapsed((previous) => {
      const next = !previous
      persistCollapsed(storageKey, next)
      return next
    })
  }

  /**
   * A RESIZE INTO the narrow width closes the rail WITHOUT storing it: it
   * would otherwise overlay the content from nothing more than a resize,
   * and a stored value would overwrite the desktop preference. A resize
   * BACK OUT restores that preference, which is why it was never stored
   * over -- reported as surprising when the rail stayed shut. Reacts to
   * transitions only: the ref starts equal to the first value, so neither
   * branch can fire on mount, which `resolveCollapsed` already decided.
   */
  const wasMobile = useRef(isMobile)
  useEffect(() => {
    const was = wasMobile.current
    wasMobile.current = isMobile
    if (isMobile && !was) setCollapsed(true)
    else if (!isMobile && was) setCollapsed(resolveCollapsed(storageKey))
  }, [isMobile, storageKey])

  /**
   * ON A NARROW SCREEN, NAVIGATING CLOSES AN EXPANDED RAIL, which would
   * otherwise stay over the page just opened. Keyed on the path ALONE --
   * keyed on `collapsed` too, expanding would re-run it and shut the rail
   * at once -- and skipping the first run, which happens on mount and
   * collapsed a stored "open" on load (caught by the test of exactly that).
   */
  const firstRun = useRef(true)
  const latest = useRef({ isMobile, collapsed })
  useEffect(() => {
    latest.current = { isMobile, collapsed }
  })
  useEffect(() => {
    if (firstRun.current) {
      firstRun.current = false
      return
    }
    if (latest.current.isMobile && !latest.current.collapsed) {
      setCollapsed(true)
      persistCollapsed(storageKey, true)
    }
  }, [location.pathname, storageKey])

  /**
   * Ctrl/Cmd+B from anywhere: the web's convention for a sidebar (GitHub,
   * VS Code, Notion, Linear) -- Ctrl+O, a reference's own, is the
   * browser's Open File. No focus guard: a modifier+letter is never text.
   */
  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        toggleCollapsed()
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  /**
   * BADGES, from the modules that activate at startup -- each only on
   * its OWN rail entries, by the paths its manifest's `nav` declares.
   */
  const badgeSources = useActivated(modules, 'onStartup', true).flatMap(({ module, code }) =>
    code.useBadges ? [{ module, useBadges: code.useBadges }] : [],
  )
  const [badgeReports, reportBadges] = useBadgeReports()
  const badges = new Map<string, Badge>()
  for (const { module } of badgeSources) {
    const reported = badgeReports.get(module.id) ?? {}
    for (const entry of module.contributes.nav ?? []) {
      const badge = reported[entry.path]
      if (badge !== undefined && badge.count > 0) badges.set(entry.path, badge)
    }
  }

  /**
   * GROUPED, NOT LISTED: a heading wherever the subject changes, in the
   * feed's order, so the grouping cannot disagree with it.
   *
   * MenuItem, not a router link: Blueprint has no vertical navbar, and a
   * vertical Menu is its pattern. A real href keeps "open in new tab";
   * the click is intercepted for a client-side transition.
   *
   * THE LABEL IS HIDDEN BY THE HOST'S CSS WITH CLIP-PATH, NOT REMOVED,
   * so it stays the accessible name of an icon-only rail -- "a link whose
   * only content is an SVG announces as nothing useful". No aria-label,
   * which would override the real text and could drift from it.
   *
   * A NATIVE `title` for the collapsed rail, not a Blueprint Tooltip:
   * wrapping each item put a popover target between the <ul> and its
   * <li>s, and in a browser every item drew at the same y -- the rail
   * seemed to hold one app. jsdom never showed it.
   */
  let lastSubject: string | undefined
  // HIDDEN TABS LEAVE THE RAIL ONLY: the navigation commands above are
  // made from the whole of `nav`, so the palette still reaches them.
  const shown = hiddenPaths === undefined ? nav : nav.filter((entry) => !hiddenPaths.has(entry.path))
  const navItems = shown.flatMap((entry) => {
    const heading =
      entry.subject && entry.subject !== lastSubject ? (
        <li className="app__nav-subject" key={`subject-${entry.subject}`} role="presentation">
          {entry.subject}
        </li>
      ) : null
    lastSubject = entry.subject
    const here = location.pathname === entry.path
    const badge = badges.get(entry.path)
    const item = (
      <MenuItem
        key={entry.path}
        icon={
          badge === undefined ? (
            iconFor(entry.path)
          ) : (
            // ON THE ICON, so a collapsed rail shows it too; the number
            // is decoration, the aria-label below is what is announced.
            <span className="app__nav-icon">
              <Icon icon={iconFor(entry.path)} />
              <span className="app__nav-badge" aria-hidden="true">
                {badgeText(badge.count)}
              </span>
            </span>
          )
        }
        text={<span className="app__nav-label">{entry.title}</span>}
        /**
         * WITH A BADGE, THE NAME SAYS IT: "Inbox, 3 waiting". An
         * aria-label, built from the entry's own title so it cannot
         * drift from the label: words in a visually hidden span came out
         * as "Inbox , 3 waiting" in Chrome, which computes an absolutely
         * positioned element as a block of its own -- jsdom did not, and
         * only the browser test showed it. Without a badge, no
         * aria-label: the label text is the name, as above.
         */
        aria-label={badge === undefined ? undefined : `${entry.title}, ${badge.label}`}
        href={entry.path}
        active={here}
        aria-current={here ? 'page' : undefined}
        title={collapsed ? entry.title : undefined}
        onClick={(event) => {
          event.preventDefault()
          void navigate(entry.path)
        }}
      />
    )
    return heading ? [heading, item] : [item]
  })

  return (
    <div className={collapsed ? 'app-frame app-frame--sidebar-collapsed' : 'app-frame'}>
      {/* THE HEADER SPANS THE WIDTH, above the rail, as the cloud
          consoles do, so the columns below start at one y. Dark chrome
          in both themes, so Blueprint widgets in it are told so. */}
      <header className={`app__header ${Classes.DARK}`}>
        <h1 className="app__header-title">{brand}</h1>
        <div className="app__header-actions">{actions}</div>
      </header>
      {overlays}
      {badgeSources.map(({ module, useBadges }) => (
        <BadgeSource key={module.id} id={module.id} useBadges={useBadges} report={reportBadges} />
      ))}
      {sources.map(({ id, usePalette }) => (
        <PaletteSource key={id} id={id} usePalette={usePalette} open={paletteOpen} report={report} />
      ))}
      <CommandPalette
        commands={allCommands}
        suggest={allSuggestions}
        isOpen={paletteOpen}
        onClose={() => setPaletteOpen(false)}
      />
      <div className="app">
        {/* THE RAIL IS ALWAYS PRESENT, at every width: a 56px rail fits a
            phone, so moving between sub-apps never costs a step, and
            "expanded" is the only state that overlays -- by the host's
            media query. Never aria-hidden: it is on screen. It holds
            navigation and nothing else, its own collapse toggle above
            the icons. */}
        <aside className={`app__sidebar ${Classes.DARK}`}>
          <button
            type="button"
            className="app__sidebar-toggle"
            onClick={toggleCollapsed}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-pressed={!collapsed}
            title={`${collapsed ? 'Expand' : 'Collapse'} sidebar (Ctrl+B or ⌘B)`}
          >
            <svg viewBox="0 0 20 20" width="18" height="18" fill="none" aria-hidden="true">
              <rect x="2.5" y="3.5" width="15" height="13" rx="2" stroke="currentColor" strokeWidth="1.4" />
              <line x1="7.5" y1="3.5" x2="7.5" y2="16.5" stroke="currentColor" strokeWidth="1.4" />
            </svg>
          </button>
          <Menu className="app__nav">{navItems}</Menu>
        </aside>
        <div className="app__content">
          {safeMode && (
            // ABOVE EVERY PAGE, not a notice that goes away: being in
            // safe mode changes what every page can do, and the way out
            // must be findable from wherever the person is.
            <div className="shell__safe-mode" role="status">
              <p>
                <strong>Safe mode.</strong> Only the system&apos;s own sub-apps are loaded, in this tab, until you
                leave it. Nothing has changed for anyone else.
              </p>
              <button type="button" className="shell__safe-mode-leave" onClick={safeMode.onLeave}>
                Leave safe mode
              </button>
            </div>
          )}
          <main>
            {/* Around the page alone, so the frame stays drawn and usable
                while a page's code loads. */}
            <Suspense fallback={fallback}>
              <Outlet />
            </Suspense>
          </main>
        </div>
      </div>
    </div>
  )
}
