import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { lazy, type ComponentType } from 'react'
import Shell, { type VisibleApp } from './Shell'

function renderShell(visibleApps: VisibleApp[], onLogout: () => void = vi.fn(), initialPath = '/query') {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <Routes>
        <Route element={<Shell visibleApps={visibleApps} onLogout={onLogout} />}>
          <Route path="/query" element={<p>query screen</p>} />
          <Route path="/admin" element={<p>admin screen</p>} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

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
    // broken shell, just a temporarily-empty one.
    expect(screen.getByText('Elysium')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
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

  it('calls onLogout when the Log out button is clicked', () => {
    const onLogout = vi.fn()
    renderShell([{ name: 'Query', path: '/query', gating_permission: null }], onLogout)
    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
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
              <Shell visibleApps={[{ name: 'Query', path: '/query', gating_permission: null }]} onLogout={onLogout} />
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

  it('keeps the persistent chrome -- header, nav, Log out -- visible and unaffected while a lazy child is still loading; this is the entire reason the boundary is scoped to Outlet alone, not the whole Shell', () => {
    const { LazyComponent } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent)
    expect(screen.getByText('Elysium')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Query' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log out' })).toBeInTheDocument()
  })

  it('the Log out button stays genuinely clickable while a lazy child is still loading, not just visually present', () => {
    const onLogout = vi.fn()
    const { LazyComponent } = createControlledLazyComponent()
    renderShellWithLazyRoute(LazyComponent, onLogout)

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))

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

    fireEvent.click(screen.getByRole('button', { name: 'Log out' }))
    expect(onLogout).toHaveBeenCalledTimes(1)
  })
})
