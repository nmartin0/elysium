import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { Classes } from '@blueprintjs/core'
import { render, screen, fireEvent, waitFor, act } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { lazy, type ComponentType } from 'react'
import type { CurrentUser } from '@elysium/shell-api/components/UserMenu'
import Shell, { type VisibleApp } from './Shell'

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'elysium.sidebarCollapsed'

function renderShell(
  visibleApps: VisibleApp[],
  onLogout: () => void = vi.fn(),
  initialPath = '/query',
  currentUser: CurrentUser | null = null,
) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<Shell visibleApps={visibleApps} currentUser={currentUser} onLogout={onLogout} />}>
          <Route path="/query" element={<p>query screen</p>} />
          <Route path="/admin" element={<p>admin screen</p>} />
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
})

describe('Shell', () => {
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
  // setupTests.js's own global default already includes them; this
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
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('defaults to COLLAPSED when matchMedia reports a narrow viewport and no stored preference exists', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(true))
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
  })

  it('a stored "true" preference overrides matchMedia entirely -- starts collapsed even on a normal-width viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(false))
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
  })

  it('a stored "false" preference overrides matchMedia entirely -- starts open even on a narrow viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(true))
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'false')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: 'Hide sidebar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Show sidebar' }))

    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
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
    fireEvent.click(screen.getByRole('button', { name: 'Hide sidebar' }))
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('true')
  })

  it('persists the expanded choice to localStorage when toggled back', () => {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Show sidebar' }))
    expect(window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)).toBe('false')
  })

  it('a real Ctrl+B keydown toggles the sidebar from anywhere, with no element focused', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b', ctrlKey: true })
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
  })

  it('a real Cmd (meta)+B keydown toggles the sidebar too', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b', metaKey: true })
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('still renders correctly, defaulting via matchMedia, when reading localStorage itself throws', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue(mockMediaQueryList(false))
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('the toggle still updates the visible state even when WRITING to localStorage throws', () => {
    vi.spyOn(window.localStorage, 'setItem').mockImplementation(() => {
      throw new Error('storage disabled')
    })
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Hide sidebar' }))
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
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
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()

    fireEvent.click(screen.getByRole('menuitem', { name: 'Admin' }))

    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
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
            element={
              <Shell
                visibleApps={[{ name: 'Query', path: '/query' }]}
                currentUser={null}
                onLogout={onLogout}
              />
            }
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

    fireEvent.click(screen.getByLabelText('Switch to dark theme'))
    expect(document.body.classList.contains(Classes.DARK)).toBe(true)

    fireEvent.click(screen.getByLabelText('Switch to light theme'))
    expect(document.body.classList.contains(Classes.DARK)).toBe(false)
  })

  it('remembers the choice', () => {
    // A theme is a preference. Re-choosing it every visit is the kind
    // of small friction that makes an app feel unfinished.
    const first = renderShell([{ name: 'Query', path: '/query' }])
    fireEvent.click(screen.getByLabelText('Switch to dark theme'))
    first.unmount()

    renderShell([{ name: 'Query', path: '/query' }])

    expect(screen.getByLabelText('Switch to light theme')).toBeInTheDocument()
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

    expect(screen.getByRole('menuitem', { name: 'Query' }))
      .toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('menuitem', { name: 'Browse' }))
      .not.toHaveAttribute('aria-current')
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
