import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { Classes } from '@blueprintjs/core'
import { act, render, screen, fireEvent, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Routes, Route, useLocation } from 'react-router-dom'
import { lazy, type ComponentType } from 'react'
import type { CurrentUser } from '@elysium/shell-api/components/UserMenu'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { getVisibleActionTypesCached } from '@elysium/shell-api/api'
import { publishHostValues, resetHostValues } from '@elysium/shell-api/host'
import { useBrowsePalette } from '@elysium/app-browse/palette'
import type { FrameModules } from '@shell/core/activation'
import { useInboxBadges } from './inbox/badges'
import { enterSafeMode, leaveSafeMode } from '@shell/core/safeMode'

/** Where the router is, for commands that navigate into Browse. */
function BrowseProbe() {
  const location = useLocation()
  return <p data-testid="at">{`${location.pathname}${location.search}`}</p>
}
import Shell, { type VisibleApp } from './Shell'

// THE PALETTE FETCHES ON OPENING -- saved views and action types -- so
// the API those come from is stubbed, and a test that opens it lets
// the answers land (openPalette below) rather than ending mid-flight.
// Entering and leaving safe mode reload the page, which jsdom cannot do:
// the reload itself is the shell's, tested in @shell/core/safeMode; here,
// only that Elysium's frame offers it.
vi.mock('@shell/core/safeMode', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@shell/core/safeMode')>()),
  enterSafeMode: vi.fn(),
  leaveSafeMode: vi.fn(),
}))

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getSavedViews: vi.fn().mockResolvedValue([]),
  getVisibleActionTypesCached: vi.fn().mockResolvedValue({}),
}))

async function openPalette(
  keys: { key: string; metaKey?: boolean; ctrlKey?: boolean },
  target: Window | Element = window,
) {
  fireEvent.keyDown(target, keys)
  // Opening loads the palette's modules (Browse's hook) and they fetch:
  // a few turns of the event loop, not one.
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)))
}

/**
 * THE MODULES AS APP.TSX GIVES THEM (step 1.3): Browse's palette hook,
 * activated when the palette opens, and the Inbox's badge, activated at
 * startup -- each only when the rail offers that sub-app, as the feed
 * would. What Browse needs of the schema is what the host publishes, not
 * a prop of the shell.
 */
function modulesFor(visibleApps: VisibleApp[]): FrameModules {
  const offered = (path: string) => visibleApps.some((app) => app.path === path)
  const entry = (id: string, path: string, events: string[]) => ({
    id,
    name: id,
    version: '1',
    contributes: { nav: [{ title: id, path }] },
    entry: null,
    activationEvents: events,
  })
  return {
    feed: [
      ...(offered('/browse') ? [entry('browse', '/browse', ['onPalette'])] : []),
      ...(offered('/inbox') ? [entry('inbox', '/inbox', ['onStartup'])] : []),
    ],
    activate: (module) =>
      module.id === 'browse'
        ? { usePalette: useBrowsePalette }
        : module.id === 'inbox'
          ? { useBadges: useInboxBadges }
          : undefined,
  }
}

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'elysium.sidebarCollapsed'

function renderShell(
  visibleApps: VisibleApp[],
  onLogout: () => void = vi.fn(),
  initialPath = '/query',
  currentUser: CurrentUser | null = null,
  visibleSchema: VisibleSchema | null = null,
) {
  act(() => publishHostValues({ visibleSchema, username: currentUser?.username ?? '', onSessionExpired: () => {} }))
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route
          element={
            <Shell
              visibleApps={visibleApps}
              modules={modulesFor(visibleApps)}
              currentUser={currentUser}
              onLogout={onLogout}
            />
          }
        >
          <Route path="/query" element={<p>query screen</p>} />
          <Route path="/admin" element={<p>admin screen</p>} />
          <Route path="/browse" element={<BrowseProbe />} />
          <Route path="/objects/:type/:id" element={<BrowseProbe />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  // A clean slate for every test -- jsdom's own real localStorage
  // implementation genuinely persists across tests within the same
  // file otherwise, which would let an earlier test's own collapsed/
  // expanded choice silently leak into a later, unrelated test's
  // "default" state.
  window.localStorage.clear()
})

afterEach(() => {
  // A REAL bug this caught directly, not a precaution taken on
  // principle: without this, a vi.spyOn(window, 'matchMedia') (or
  // localStorage) override from one test was still active in the
  // NEXT test that never set its own -- confirmed by watching 6
  // tests fail from exactly this leak, then pass once this was
  // added.
  vi.restoreAllMocks()
  act(() => resetHostValues())
})

describe('Shell', () => {
  it('opens the help assistant from the header', async () => {
    renderShell([{ name: 'Query', path: '/query' }])

    fireEvent.click(screen.getByRole('button', { name: 'Help' }))

    expect(await screen.findByLabelText('Your question')).toBeInTheDocument()
  })

  it('renders nav links exactly matching the visibleApps it was given', () => {
    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Browse', path: '/browse' },
    ])
    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Browse' })).toBeInTheDocument()
    expect(screen.queryByRole('menuitem', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('renders no nav links at all for an empty visibleApps -- the deliberate default before the fetch resolves', () => {
    renderShell([])
    expect(screen.queryAllByRole('menuitem')).toHaveLength(0)
    // Still renders the rest of the chrome -- an empty nav isn't a
    // broken shell, just a temporarily-empty one. The user menu
    // trigger is always present regardless of nav content -- "Account"
    // is its own real, predictable label here since these tests all
    // pass the default currentUser={null}.
    expect(screen.getByText('Elysium')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
  })

  it('shows Admin only when it is actually present in visibleApps', () => {
    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Admin', path: '/admin' },
    ])
    expect(screen.getByRole('menuitem', { name: 'Admin' })).toBeInTheDocument()
  })

  it('renders the correct child route inside Outlet for the current path', () => {
    renderShell([{ name: 'Admin', path: '/admin' }], vi.fn(), '/admin')
    expect(screen.getByText('admin screen')).toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('calls onLogout when Log out is clicked inside the (now real, dropdown) user menu', () => {
    const onLogout = vi.fn()
    renderShell([{ name: 'Query', path: '/query' }], onLogout)
    fireEvent.click(screen.getByRole('button', { name: 'Account' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})

// The collapsible sidebar -- #2 of the shell/launcher upgrade plan.
// Real behavior, not just markup: an initial state resolved from
// localStorage (falling back to a real matchMedia check when no
// stored value exists), a toggle that both updates the visual state
// and persists it, a keyboard shortcut, and defensive handling when
// storage itself is unavailable -- each tested directly against its
// own real, observable effect, not inferred from the source.
describe('Shell -- the collapsible sidebar', () => {
  const VISIBLE_APPS: VisibleApp[] = [{ name: 'Query', path: '/query' }]

  // Shell.tsx's own live matchMedia listener (addEventListener/
  // removeEventListener, added for the mobile Drawer step) needs
  // BOTH of those methods present on whatever matchMedia() returns --
  // the test setup's own global default (packages/testing/src/
  // setup.ts) already includes them; this
  // helper is what keeps THIS file's own per-test overrides
  // (mockReturnValue) from silently dropping them again, the same
  // real TypeError caught directly the first time this file's own
  // plain `{ matches } as MediaQueryList` casts ran against real code
  // that now calls addEventListener, not assumed upfront.
  function mockMediaQueryList(matches: boolean): MediaQueryList {
    return {
      matches,
      media: '(max-width: 640px)',
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as MediaQueryList
  }

  it('defaults to OPEN when matchMedia reports a normal-width viewport and no stored preference exists', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(false))
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('defaults to COLLAPSED when matchMedia reports a narrow viewport and no stored preference exists', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(true))
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('a stored "true" preference overrides matchMedia entirely -- starts collapsed even on a normal-width viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(false))
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('a stored "false" preference overrides matchMedia entirely -- starts open even on a narrow viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(true))
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'false')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('collapsing leaves the rail reachable by assistive technology', () => {
    /**
     * This used to assert the OPPOSITE -- that collapsing set
     * aria-hidden -- and that was right when collapsing meant width
     * 0. A rail is on screen, so hiding it from assistive technology
     * makes the navigation invisible to exactly the users the
     * visible-label work was for.
     */
    renderShell([{ name: 'Query', path: '/query' }])

    fireEvent.click(screen.getByLabelText(/sidebar/i))

    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('clicking the toggle again re-expands the sidebar', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }))

    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('REPEATED clicks on the toggle button correctly alternate every time too, the same real fix as the keyboard shortcut -- toggleCollapsed() is shared code, so this confirms the fix holds for both real trigger paths, not just the one the bug reproduction happened to use', () => {
    renderShell(VISIBLE_APPS)
    const toggle = () => screen.getByRole('button', { name: /sidebar/i })
    expect(toggle().getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(toggle())
    expect(toggle().getAttribute('aria-pressed')).toBe('false')

    fireEvent.click(toggle())
    expect(toggle().getAttribute('aria-pressed')).toBe('true')

    fireEvent.click(toggle())
    expect(toggle().getAttribute('aria-pressed')).toBe('false')
  })

  it('persists the collapsed choice to localStorage when toggled', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('true')
  })

  it('persists the expanded choice to localStorage when toggled back', () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('false')
  })

  it('a real Ctrl+B keydown toggles the sidebar from anywhere, with no element focused', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true })
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('a real Cmd (meta)+B keydown toggles the sidebar too', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b', metaKey: true })
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })

  it('REPEATED, separate Cmd+B presses correctly alternate every time, not just the first -- a real, severe, previously-shipped bug (a stale closure meant the shortcut only ever worked once, then got permanently stuck), confirmed fixed with a real, repeated reproduction, not a single press the way the two tests above only ever exercised', () => {
    renderShell(VISIBLE_APPS)
    const toggle = () => screen.getByRole('button', { name: /sidebar/i })
    expect(toggle().getAttribute('aria-pressed')).toBe('true')

    fireEvent.keyDown(window, { key: 'b', metaKey: true })
    expect(toggle().getAttribute('aria-pressed')).toBe('false')

    fireEvent.keyDown(window, { key: 'b', metaKey: true })
    expect(toggle().getAttribute('aria-pressed')).toBe('true')

    fireEvent.keyDown(window, { key: 'b', metaKey: true })
    expect(toggle().getAttribute('aria-pressed')).toBe('false')
  })

  it('an unmodified "b" keydown -- no Ctrl or Cmd -- does NOT toggle the sidebar', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b' })
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('still renders correctly, defaulting via matchMedia, when reading localStorage itself throws', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(false))
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })

  it('the toggle still updates the visible state even when WRITING to localStorage throws', () => {
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('button', { name: 'Expand sidebar' })).toBeInTheDocument()
  })
})

// The mobile Drawer -- a real, live matchMedia listener now, not the
// prior one-time-at-mount-only check, plus a genuine container swap
// (Drawer on mobile, the same in-flow <aside> as before on desktop).
// Neither Drawer nor <aside> carries a distinguishing ARIA role of its
// own (confirmed directly, not assumed -- inspected Drawer's own real
// rendered output before writing any of this: no role="dialog" or
// similar, just .bp6-drawer as a real, structural marker), so these
// tests query by that real class rather than by role.
describe('Shell -- the mobile Drawer', () => {
  const VISIBLE_APPS: VisibleApp[] = [
    { name: 'Query', path: '/query' },
    { name: 'Admin', path: '/admin' },
  ]

  // Captures the real callback passed to addEventListener('change',
  // ...) so a test can invoke it directly, exactly the way a real
  // browser would when the viewport actually crosses the breakpoint
  // -- not just asserting the initial, one-time value the way the
  // describe block above already covers.
  //
  // A real, second fix needed here, not just the first: Shell.tsx now
  // reads isMobile via useSyncExternalStore, which re-invokes
  // getIsMobileSnapshot() (a fresh window.matchMedia(...).matches
  // read) whenever the subscribed callback fires -- it does NOT read
  // anything off the fake event object passed to that callback the
  // way the prior, direct-useState implementation used to. A plain
  // `matches: initialMatches` field, mutated nowhere, meant every
  // later getSnapshot() call kept returning the SAME, stale value
  // regardless of what simulateChange() claimed to change it to --
  // confirmed directly (a live-switch test failed, still showing the
  // desktop <aside>, after simulating a change to true). Fixed with a
  // real getter backing `matches`, which is still genuinely read-only
  // from any consumer's own perspective (there is no setter) while
  // letting this helper's own internal, mutable currentMatches
  // actually drive what every later matchMedia().matches read
  // returns.
  function mockLiveMediaQueryList(initialMatches: boolean) {
    let currentMatches = initialMatches
    let changeHandler: ((event: MediaQueryListEvent) => void) | null = null
    const mql = {
      get matches() {
        return currentMatches
      },
      media: '(max-width: 640px)',
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: (type: string, handler: (event: MediaQueryListEvent) => void) => {
        if (type === 'change') changeHandler = handler
      },
      removeEventListener: () => {},
      dispatchEvent: () => false,
    } as MediaQueryList
    return {
      mql,
      simulateChange(matches: boolean) {
        currentMatches = matches
        changeHandler?.({ matches } as MediaQueryListEvent)
      },
    }
  }

  it('renders the in-flow <aside>, not a Drawer, on a normal-width viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockLiveMediaQueryList(false).mql)
    renderShell(VISIBLE_APPS)
    expect(document.querySelector('aside.app__sidebar')).not.toBeNull()
    expect(document.querySelector('.bp6-drawer')).toBeNull()
  })

  it('keeps the sidebar present on a narrow viewport', () => {
    /**
     * A Drawer used to take over below 640px, and closing it left no
     * way back to the app switcher -- the sidebar was simply gone.
     *
     * The rail removed the reason for it. 56px fits a phone, so the
     * sidebar is present at every width and only the EXPANDED state
     * needs to overlay, which is a media query rather than a
     * component. Moving between sub-apps never costs a step.
     */
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockLiveMediaQueryList(true).mql)

    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.querySelector('aside.app__sidebar')).not.toBeNull()

    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('shows every app in the rail, not just the first', () => {
    // The sidebar scrolls itself. Without that, the shell's own
    // overflow:hidden clipped the nav and only the first item showed
    // -- reported exactly that way.
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockLiveMediaQueryList(true).mql)

    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Browse', path: '/browse' },
      { name: 'Schema', path: '/schema' },
    ])

    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Browse' })).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Schema' })).toBeInTheDocument()
  })

  it('navigating does not dismiss the rail', () => {
    // The Drawer auto-closed on navigation because it covered the
    // content. A rail does not cover anything, so there is nothing to
    // dismiss -- and dismissing it would take away the app switcher
    // the rail exists to keep.
    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Admin', path: '/admin' },
    ])

    fireEvent.click(screen.getByRole('menuitem', { name: 'Admin' }))

    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('does NOT auto-close the desktop sidebar on navigation -- the effect above is mobile-only, confirmed directly, not just assumed from the isMobile check reading correctly', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockLiveMediaQueryList(false).mql)
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: 'Admin' }))

    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
    expect(screen.getByText('admin screen')).toBeInTheDocument()
  })
})

// Shell.tsx's own <Suspense> boundary, wrapping ONLY <Outlet /> --
// added alongside App.tsx's lazy-loaded sub-app routes. A REAL,
// previously-missing gap: the existing tests above render every
// child route as a plain, already-resolved element (e.g. `<p>query
// screen</p>`), which never genuinely suspends at all -- confirming
// the chrome renders correctly says nothing about whether the
// Suspense boundary itself is scoped correctly. These tests use a
// real React.lazy() component whose own module resolution is
// deliberately held open via a controllable promise -- the same
// "let resolveX" pattern already established elsewhere in this
// codebase's own tests (LoginForm.test.tsx, PendingWriteCard.test.
// tsx) -- to observe a genuine, real in-flight loading state, not
// just infer it from the code.
describe('Shell -- the Suspense boundary around lazy-loaded sub-app routes', () => {
  function createControlledLazyComponent() {
    let resolveImport: (module: { default: ComponentType }) => void
    const LazyComponent = lazy(
      () =>
        new Promise<{ default: ComponentType }>((resolve) => {
          resolveImport = resolve
        }),
    )
    return {
      LazyComponent,
      // resolveImport! -- genuinely safe by construction, not assumed:
      // the lazy() executor above runs synchronously, on the very
      // first render attempt, so resolveImport is always already
      // assigned by the time any test calls resolve().
      resolve: () => resolveImport!({ default: () => <p>slow screen loaded</p> }),
    }
  }

  function renderShellWithLazyRoute(LazyComponent: ComponentType, onLogout: () => void = vi.fn()) {
    return render(
      <MemoryRouter initialEntries={['/slow']}>
        <Routes>
          <Route
            element={<Shell visibleApps={[{ name: 'Query', path: '/query' }]} currentUser={null} onLogout={onLogout} />}
          >
            <Route path="/slow" element={<LazyComponent />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('shows the Suspense fallback while a lazy child route is still loading', () => {
    const { LazyComponent } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('keeps the persistent chrome -- header, nav, user menu -- visible and unaffected while a lazy child is still loading; this is the entire reason the boundary is scoped to Outlet alone, not the whole Shell', () => {
    const { LazyComponent } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent)
    expect(screen.getByText('Elysium')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Account' })).toBeInTheDocument()
  })

  it('Log out stays genuinely reachable through the user menu while a lazy child is still loading, not just visually present', () => {
    const onLogout = vi.fn()
    const { LazyComponent } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent, onLogout)

    fireEvent.click(screen.getByRole('button', { name: 'Account' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))

    expect(onLogout).toHaveBeenCalledTimes(1)
  })

  it('replaces the fallback with the real, resolved content once the lazy import completes', async () => {
    const { LazyComponent, resolve } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent)
    expect(screen.getByText('Loading…')).toBeInTheDocument()

    resolve()

    await waitFor(() => expect(screen.getByText('slow screen loaded')).toBeInTheDocument())
    expect(screen.queryByText('Loading…')).not.toBeInTheDocument()
  })

  it('the chrome remains fully intact, and Log out still works, after the lazy content has loaded -- not just before', async () => {
    const onLogout = vi.fn()
    const { LazyComponent, resolve } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent, onLogout)

    resolve()
    await waitFor(() => expect(screen.getByText('slow screen loaded')).toBeInTheDocument())

    fireEvent.click(screen.getByRole('button', { name: 'Account' }))
    fireEvent.click(screen.getByRole('menuitem', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})

describe('theme', () => {
  // Asserts Blueprint's OWN class constant. A first version hardcoded
  // 'bp5-dark' -- which our own toggle also set, so the test passed
  // while Blueprint 6, which emits bp6-dark, saw nothing at all.
  it('turns dark mode on and off', () => {
    // Blueprint carries a dark variant on every widget and nothing
    // turned it on. Applied as a body class so those variants and
    // tokens.css's dark surfaces switch together.
    renderShell([{ name: 'Query', path: '/query' }])

    fireEvent.click(screen.getByLabelText('Switch to light theme'))
    expect(document.body.classList.contains(Classes.DARK)).toBe(false)

    fireEvent.click(screen.getByLabelText('Switch to dark theme'))
    expect(document.body.classList.contains(Classes.DARK)).toBe(true)
  })

  it('starts dark when nobody has chosen (DEV_UI 8.6.6)', () => {
    localStorage.clear()
    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.body.classList.contains(Classes.DARK)).toBe(true)
    expect(screen.getByLabelText('Switch to light theme')).toBeInTheDocument()
  })

  it('remembers the choice', () => {
    // A theme is a preference. Re-choosing it every visit is the kind
    // of small friction that makes an app feel unfinished.
    const first = renderShell([{ name: 'Query', path: '/query' }])
    fireEvent.click(screen.getByLabelText('Switch to light theme'))
    first.unmount()

    renderShell([{ name: 'Query', path: '/query' }])

    expect(screen.getByLabelText('Switch to dark theme')).toBeInTheDocument()
  })

  it('a light theme stored by the old, always-written key is not a choice', () => {
    // Every browser held `theme: light` without anyone choosing it; a
    // default that could not reach them would not be a default.
    localStorage.clear()
    localStorage.setItem('elysium.pref.theme.', JSON.stringify('light'))
    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.body.classList.contains(Classes.DARK)).toBe(true)
  })
})

describe('the inbox badge (DEV_UI 15.3)', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function answering(counts: { approvals: number; notifications: number; identity: number }) {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        String(url).endsWith('/me/inbox')
          ? new Response(JSON.stringify(counts), { status: 200 })
          : new Response('{}', { status: 404 }),
      ),
    )
  }

  // ON THE INBOX'S RAIL ENTRY, its own badge (step 1.3c): the owner chose
  // the rail as its only place, present at every width.
  const RAIL = [
    { name: 'Query', path: '/query' },
    { name: 'Inbox', path: '/inbox' },
  ]

  it('shows how much is waiting, on every screen', async () => {
    answering({ approvals: 2, notifications: 1, identity: 1 })
    renderShell(RAIL)

    const inbox = await screen.findByRole('menuitem', { name: 'Inbox, 4 waiting' })
    expect(inbox.querySelector('.app__nav-badge')).toHaveTextContent('4')
  })

  it('says nothing when nothing is waiting -- no zero badge', async () => {
    answering({ approvals: 0, notifications: 0, identity: 0 })
    renderShell(RAIL)
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)))

    expect(screen.getByRole('menuitem', { name: 'Inbox' })).toBeInTheDocument()
    expect(document.querySelector('.app__nav-badge')).toBeNull()
  })

  it('is in the rail, not the header', async () => {
    answering({ approvals: 1, notifications: 0, identity: 0 })
    renderShell(RAIL)
    await screen.findByRole('menuitem', { name: 'Inbox, 1 waiting' })

    expect(document.querySelector('header')!.textContent).not.toMatch(/Inbox|1/)
  })
})

describe('row density (DEV_UI 9.3)', () => {
  it('is middle until somebody chooses', () => {
    localStorage.clear()
    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.body.dataset.density).toBe('middle')
  })

  it('a stored value that is not a density falls back to middle', () => {
    localStorage.clear()
    localStorage.setItem('elysium.pref.density.', JSON.stringify('spacious'))
    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.body.dataset.density).toBe('middle')
  })

  it('a stored choice is applied', () => {
    localStorage.clear()
    localStorage.setItem('elysium.pref.density.', JSON.stringify('compact'))
    renderShell([{ name: 'Query', path: '/query' }])

    expect(document.body.dataset.density).toBe('compact')
  })
})

describe('the app rail', () => {
  const APPS = [
    { name: 'Query', path: '/query' },
    { name: 'Browse', path: '/browse' },
  ]

  it('gives every app an icon', () => {
    // A rail item with no icon collapses to an empty box.
    renderShell(APPS)

    expect(document.querySelector('[data-icon="chat"]')).toBeTruthy()
    expect(document.querySelector('[data-icon="search"]')).toBeTruthy()
  })

  it('names the app even when the label is hidden', () => {
    /**
     * Icon-only navigation is documented as the highest-failure
     * sidebar pattern, precisely because teams drop the accessible
     * name along with the visible one -- "a link whose only content is
     * an SVG announces as nothing useful".
     *
     * The name comes from the label TEXT, which clip-path hides
     * visually while leaving it in the accessibility tree. Worth
     * saying what this cannot check: jsdom applies no stylesheet, so
     * the hiding itself is unverified here -- theme.test.ts asserts on
     * the CSS instead.
     */
    renderShell(APPS)

    expect(screen.getByRole('menuitem', { name: 'Query' })).toBeInTheDocument()
  })

  it('marks the current app for assistive technology', () => {
    // `active` alone is a visual state; aria-current is what a screen
    // reader announces.
    // /query, because the test harness only routes paths it declares
    // -- an undeclared one renders nothing and the assertion would
    // fail for the wrong reason.
    renderShell(APPS, vi.fn(), '/query')

    expect(screen.getByRole('menuitem', { name: 'Query' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('menuitem', { name: 'Browse' })).not.toHaveAttribute('aria-current')
  })
})

describe('app icons', () => {
  it('gives Query the conversational icon and Browse the search one', async () => {
    /**
     * Chosen for what each app DOES, not what it is called. Query is
     * the natural-language surface; Browse is the one with a search
     * box. The intuitive reading of the words alone puts them the
     * other way round, which would leave a magnifying glass on the app
     * with no search in it.
     */
    const { iconForApp } = await import('@elysium/shell-api/appIcons')

    expect(iconForApp('/query')).toBe('chat')
    expect(iconForApp('/browse')).toBe('search')
  })

  it('falls back rather than rendering nothing', async () => {
    // A new sub-app should look unfamiliar, not broken.
    const { iconForApp } = await import('@elysium/shell-api/appIcons')

    expect(iconForApp('/something-new')).toBe('application')
  })
})

describe('the collapsed rail lays its items out as a list', () => {
  it('renders one <li> per app, directly inside the menu', () => {
    /**
     * THE bug the tests could not see, and the reason they could not.
     *
     * Every existing test rendered the EXPANDED sidebar. Collapsed, an
     * earlier version wrapped each MenuItem in a Blueprint <Tooltip>,
     * which put a popover target between the <ul> and its <li>
     * children and broke the list layout -- all three items painted at
     * the same y, stacked, so the rail appeared to hold one app.
     *
     * Found from the live DOM (every item reported top: 44) after
     * three rounds of guessing at CSS.
     *
     * Asserts STRUCTURE rather than position, because jsdom computes
     * no layout: a <ul> whose direct children are <li> lays out as a
     * list; one with anything else between them does not.
     */
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')

    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Browse', path: '/browse' },
      { name: 'Schema', path: '/schema' },
    ])

    const menu = document.querySelector('.app__nav')
    const children = [...(menu?.children ?? [])]

    expect(children).toHaveLength(3)
    expect(children.every((child) => child.tagName === 'LI')).toBe(true)
  })

  it('still names each app when only the icon is visible', () => {
    // The label survives in the accessibility tree; title covers the
    // sighted user hovering an icon.
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')

    renderShell([{ name: 'Browse', path: '/browse' }])

    const link = screen.getByRole('menuitem', { name: 'Browse' })
    expect(link).toHaveAttribute('title', 'Browse')
  })
})

describe('the global header', () => {
  const APPS = [{ name: 'Query', path: '/query' }]

  it('carries the global actions, not the rail', () => {
    /**
     * The documented division: a global header is "a mandatory element
     * in every application", carrying the product name and global
     * actions -- help, notifications, settings, user profile -- while
     * the rail carries only the top-level sections.
     *
     * It also fixes the ragged heights: with the header above
     * everything, the rail and both sub-app panes start at the same y.
     */
    renderShell(APPS)
    const header = document.querySelector('.app__header')

    expect(header).not.toBeNull()
    expect(header?.textContent).toContain('Elysium')
    expect(header?.querySelector('[aria-label*="theme"]')).not.toBeNull()
  })

  it('leaves the rail holding nothing but navigation', () => {
    // A rail that also held the theme toggle and user menu is a rail
    // doing two jobs, and it is why the columns started at different
    // heights.
    renderShell(APPS)
    const sidebar = document.querySelector('.app__sidebar')

    expect(sidebar?.querySelector('[aria-label*="theme"]')).toBeNull()
    expect(sidebar?.querySelector('.app__nav')).not.toBeNull()
  })

  it('sits above the columns, not inside them', () => {
    // Above rather than beside is what makes the three columns below
    // align. Beside would leave the rail starting higher than the
    // panes again.
    renderShell(APPS)

    const header = document.querySelector('.app__header')
    const columns = document.querySelector('.app')

    expect(header?.parentElement).toBe(columns?.parentElement)
    expect(header?.nextElementSibling).toBe(columns)
  })
})

describe('the collapse toggle belongs to the rail', () => {
  it('renders inside the sidebar, not beside it', () => {
    /**
     * It used to sit in the content area, because a collapsed sidebar
     * had width 0 and nothing inside it was reachable -- so the one
     * control that could bring it back had to live somewhere always
     * present.
     *
     * The rail removed that constraint. Outside, the button occupied a
     * bordered rectangle of its own in the canvas, which wasted width
     * and read as unrelated to the thing it changes.
     */
    renderShell([{ name: 'Query', path: '/query' }])

    const sidebar = document.querySelector('.app__sidebar')

    expect(sidebar?.querySelector('.app__sidebar-toggle')).not.toBeNull()
  })

  it('sits above the app icons', () => {
    // A control that changes the rail reads as belonging to it when it
    // heads the rail, not when it trails the list it resizes.
    renderShell([{ name: 'Query', path: '/query' }])

    const sidebar = document.querySelector('.app__sidebar')
    const [first] = [...(sidebar?.children ?? [])]

    expect(first?.className).toContain('app__sidebar-toggle')
  })

  it('says collapse rather than hide, because that is what it does', () => {
    // The old wording was accurate when collapsing meant width 0. It
    // becomes a rail now, and a label that promises hiding describes
    // something else.
    renderShell([{ name: 'Query', path: '/query' }])

    expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument()
  })
})

describe('Shell -- the command palette', () => {
  /**
   * WHAT IS BEING TESTED HERE AND NOT IN CommandPalette.test.tsx. The
   * palette's own behaviour -- matching, the keyboard, disabled commands
   * -- is tested beside the component. This covers only the wiring the
   * SHELL owns: the binding, the guard that stops it firing mid-typing,
   * and the fact that the commands come from the rail the server sent.
   *
   * THE SHELL IS WHERE IT LIVES because DEV_UI.md 10.1 quotes
   * Superhuman's own guidance to make the palette available EVERYWHERE,
   * and a palette that works on four screens out of seven is one people
   * stop reaching for. Mounting it here is what makes that true, so it
   * is worth a test that it is actually mounted here.
   */
  it('is closed until asked for -- no dialog on a fresh render', () => {
    renderShell([{ name: 'Query', path: '/query' }])
    expect(screen.queryByLabelText('Search commands')).not.toBeInTheDocument()
  })

  it('opens on Cmd-K', async () => {
    renderShell([{ name: 'Query', path: '/query' }])
    await openPalette({ key: 'k', metaKey: true })
    expect(screen.getByLabelText('Search commands')).toBeInTheDocument()
  })

  it('opens on Ctrl-K as well, so the binding does not depend on reading a user-agent string', async () => {
    renderShell([{ name: 'Query', path: '/query' }])
    await openPalette({ key: 'k', ctrlKey: true })
    expect(screen.getByLabelText('Search commands')).toBeInTheDocument()
  })

  it('ignores a bare k, which is a letter somebody is typing', () => {
    renderShell([{ name: 'Query', path: '/query' }])
    fireEvent.keyDown(window, { key: 'k' })
    expect(screen.queryByLabelText('Search commands')).not.toBeInTheDocument()
  })

  /**
   * THE BUG A BROWSER FOUND AND JSDOM COULD NOT. The listener first
   * refused every keystroke arriving from a field, applying 10.1's
   * "never fire a global shortcut while the person is typing" to a
   * binding the rule was never about. Query takes focus into its
   * question box on arrival, so Cmd-K did nothing on the screen people
   * land on -- "a palette that works on four screens out of seven is
   * one people stop reaching for", caused by the rule meant to prevent
   * something else.
   *
   * A MODIFIER-QUALIFIED BINDING CANNOT BE TYPED, which is why
   * Cmd/Ctrl-K was the binding chosen. The typing guard still exists
   * and still matters -- it is in `mayFireGlobally`, with its own tests
   * for the unmodified case, waiting for the first binding it applies
   * to.
   */
  it('opens from inside a text field, because a field is where people already are', async () => {
    renderShell([{ name: 'Query', path: '/query' }])
    const typing = document.createElement('input')
    document.body.appendChild(typing)

    await openPalette({ key: 'k', metaKey: true }, typing)

    expect(screen.getByLabelText('Search commands')).toBeInTheDocument()
    typing.remove()
  })

  it('ignores an unmodified key from a field, which is somebody typing', () => {
    renderShell([{ name: 'Query', path: '/query' }])
    const typing = document.createElement('input')
    document.body.appendChild(typing)

    fireEvent.keyDown(typing, { key: 'k' })

    expect(screen.queryByLabelText('Search commands')).not.toBeInTheDocument()
    typing.remove()
  })

  it('offers the apps the server said this caller may see, and no others', async () => {
    renderShell([
      { name: 'Query', path: '/query' },
      { name: 'Admin', path: '/admin' },
    ])
    await openPalette({ key: 'k', metaKey: true })

    // The SCREENS are exactly the rail's; the shell's own commands
    // (help, theme, density, log out) are there for everybody.
    const screens = screen
      .getAllByRole('option')
      .map((node) => node.textContent ?? '')
      .filter((label) => !label.startsWith('Shell'))
    expect(screens).toHaveLength(2)
    expect(screens.join(' ')).toContain('Query')
    expect(screens.join(' ')).toContain('Admin')
  })

  it('groups each command under the subject its app belongs to', async () => {
    // The rail is a SUBJECT switcher (DEV_UI.md 12), and the palette
    // should say the same words the rail does rather than inventing a
    // second vocabulary for the same screens.
    renderShell([{ name: 'Admin', path: '/admin', subject: 'Settings' }])
    await openPalette({ key: 'k', metaKey: true })

    expect(screen.getAllByRole('option')[0]!.textContent).toBe('SettingsAdmin')
  })

  it('navigates when a command is chosen, and closes behind itself', async () => {
    renderShell(
      [
        { name: 'Query', path: '/query' },
        { name: 'Admin', path: '/admin' },
      ],
      vi.fn(),
      '/query',
    )
    await openPalette({ key: 'k', metaKey: true })

    const admin = screen.getAllByRole('option').find((node) => node.textContent?.includes('Admin'))!
    fireEvent.click(admin)

    expect(await screen.findByText('admin screen')).toBeInTheDocument()
    await waitFor(() => expect(screen.queryByLabelText('Search commands')).not.toBeInTheDocument())
  })
})

describe('Shell -- what the palette offers beyond the rail (DEV_UI 10.1)', () => {
  const SCHEMA: VisibleSchema = { Customer: { fields: {} } }
  const options = () => screen.getAllByRole('option').map((node) => node.textContent ?? '')

  it('a type to browse, when Browse is a screen this reader has', async () => {
    renderShell([{ name: 'Browse', path: '/browse' }], vi.fn(), '/query', null, SCHEMA)
    await openPalette({ key: 'k', metaKey: true })

    fireEvent.click(screen.getAllByRole('option').find((node) => node.textContent?.includes('Browse Customer'))!)
    expect(await screen.findByTestId('at')).toHaveTextContent('/browse?type=Customer')
  })

  it('no types, and no searches, for a reader without Browse', async () => {
    renderShell([{ name: 'Query', path: '/query' }], vi.fn(), '/query', null, SCHEMA)
    await openPalette({ key: 'k', metaKey: true })
    expect(options().join(' ')).not.toMatch(/Customer/)
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'ada' } })
    // No SEARCH, which is Browse's: a shell command may still match the
    // letters ("Reload in safe mode" holds a, d, a in order).
    expect(options().join(' ')).not.toMatch(/Search/)
  })

  it('a search in the type, from whatever was typed', async () => {
    renderShell([{ name: 'Browse', path: '/browse' }], vi.fn(), '/query', null, SCHEMA)
    await openPalette({ key: 'k', metaKey: true })
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'ada' } })

    fireEvent.click(screen.getAllByRole('option').find((node) => node.textContent?.includes('Search Customer'))!)
    expect(await screen.findByTestId('at')).toHaveTextContent('/browse?type=Customer&q=ada')
  })

  it("the actions on the object in front of them, and only on that object's page", async () => {
    vi.mocked(getVisibleActionTypesCached).mockResolvedValue({
      Escalate: { affected_object_types: ['Customer'], executable: true },
    })
    renderShell([{ name: 'Browse', path: '/browse' }], vi.fn(), '/objects/Customer/c1', null, SCHEMA)
    await openPalette({ key: 'k', metaKey: true })

    expect(options()[0]).toBe('Actions · this CustomerEscalate')
    fireEvent.click(screen.getAllByRole('option')[0]!)
    expect(await screen.findByTestId('at')).toHaveTextContent('/objects/Customer/c1?action=Escalate')
  })

  it("the theme, by the toggle's own words", async () => {
    renderShell([{ name: 'Query', path: '/query' }])
    await openPalette({ key: 'k', metaKey: true })
    fireEvent.click(screen.getAllByRole('option').find((node) => node.textContent === 'ShellSwitch to light theme')!)
    await waitFor(() => expect(document.body.classList.contains(Classes.DARK)).toBe(false))
  })
})

describe('safe mode (step 1.4b)', () => {
  function renderSafe(safeMode: boolean) {
    return render(
      <MemoryRouter initialEntries={['/query']}>
        <Routes>
          <Route
            element={
              <Shell
                visibleApps={[{ name: 'Query', path: '/query' }]}
                safeMode={safeMode}
                currentUser={{ username: 'ada' } as CurrentUser}
                onLogout={vi.fn()}
              />
            }
          >
            <Route path="/query" element={<p>query screen</p>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
  }

  it('is offered from the user menu, which reloads into it', async () => {
    renderSafe(false)
    fireEvent.click(screen.getByRole('button', { name: /ada/i }))
    fireEvent.click(await screen.findByRole('menuitem', { name: 'Reload in safe mode' }))
    expect(enterSafeMode).toHaveBeenCalled()
  })

  it('is offered from the palette, by the same words', async () => {
    renderSafe(false)
    await openPalette({ key: 'k', ctrlKey: true })
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toContain('ShellReload in safe mode')
  })

  it('in it, every page says so, and the banner, the menu and the palette all lead out', async () => {
    vi.mocked(leaveSafeMode).mockClear()
    renderSafe(true)
    const banner = screen.getByText('Safe mode.').closest('[role="status"]') as HTMLElement
    fireEvent.click(within(banner).getByRole('button', { name: 'Leave safe mode' }))
    expect(leaveSafeMode).toHaveBeenCalledTimes(1)

    await openPalette({ key: 'k', ctrlKey: true })
    expect(screen.getAllByRole('option').map((o) => o.textContent)).toContain('ShellLeave safe mode')
  })
})
