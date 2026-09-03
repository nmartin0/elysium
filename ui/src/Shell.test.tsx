import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
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
      { name: 'Query', path: '/query', gating_permission: null },
      { name: 'Browse', path: '/browse', gating_permission: null },
    ])
    expect(screen.getByRole('link', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Browse' })).toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Admin' })).not.toBeInTheDocument()
  })

  it('renders no nav links at all for an empty visibleApps -- the deliberate default before the fetch resolves', () => {
    renderShell([])
    expect(screen.queryAllByRole('link')).toHaveLength(0)
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
      { name: 'Query', path: '/query', gating_permission: null },
      { name: 'Admin', path: '/admin', gating_permission: 'manage:users' },
    ])
    expect(screen.getByRole('link', { name: 'Admin' })).toBeInTheDocument()
  })

  it('renders the correct child route inside Outlet for the current path', () => {
    renderShell([{ name: 'Admin', path: '/admin', gating_permission: 'manage:users' }], vi.fn(), '/admin')
    expect(screen.getByText('admin screen')).toBeInTheDocument()
    expect(screen.queryByText('query screen')).not.toBeInTheDocument()
  })

  it('calls onLogout when Log out is clicked inside the (now real, dropdown) user menu', () => {
    const onLogout = vi.fn()
    renderShell([{ name: 'Query', path: '/query', gating_permission: null }], onLogout)
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
  const VISIBLE_APPS: VisibleApp[] = [{ name: 'Query', path: '/query', gating_permission: null }]

  it('defaults to OPEN when matchMedia reports a normal-width viewport and no stored preference exists', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('defaults to COLLAPSED when matchMedia reports a narrow viewport and no stored preference exists', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
  })

  it('a stored "true" preference overrides matchMedia entirely -- starts collapsed even on a normal-width viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'true')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
  })

  it('a stored "false" preference overrides matchMedia entirely -- starts open even on a narrow viewport', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: true } as MediaQueryList)
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, 'false')
    renderShell(VISIBLE_APPS)
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('clicking the toggle collapses the sidebar and hides it from assistive tech', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Hide sidebar' }))

    expect(screen.getByRole('button', { name: 'Show sidebar' })).toBeInTheDocument()
    // The sidebar's own nav is still technically in the DOM (aria-
    // hidden, not unmounted) -- querying via role correctly reflects
    // aria-hidden by excluding it, the real, accessible signal that
    // it's no longer reachable, not just visually smaller.
    expect(screen.queryByRole('link', { name: 'Query' })).not.toBeInTheDocument()
  })

  it('clicking the toggle again re-expands the sidebar', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.click(screen.getByRole('button', { name: 'Hide sidebar' }))
    fireEvent.click(screen.getByRole('button', { name: 'Show sidebar' }))

    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Query' })).toBeInTheDocument()
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

  it('an unmodified "b" keydown -- no Ctrl or Cmd -- does NOT toggle the sidebar', () => {
    renderShell(VISIBLE_APPS)
    fireEvent.keyDown(window, { key: 'b' })
    expect(screen.getByRole('button', { name: 'Hide sidebar' })).toBeInTheDocument()
  })

  it('still renders correctly, defaulting via matchMedia, when reading localStorage itself throws', () => {
    vi.spyOn(window, 'matchMedia').mockReturnValue({ matches: false } as MediaQueryList)
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
                visibleApps={[{ name: 'Query', path: '/query', gating_permission: null }]}
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
    expect(screen.getByRole('link', { name: 'Query' })).toBeInTheDocument()
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
