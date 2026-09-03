import { lazy, useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginForm from '@elysium/shell-api/components/LoginForm'
import Shell, { type VisibleApp } from './Shell'
import type { VisibleSchema } from '@elysium/app-browse/ObjectDetailPanel'
import { logout, getMyVisibleSchema, getVisibleApps, handleIfSessionExpired } from '@elysium/shell-api/api'
import '@elysium/shell-api/index.css'

// Lazy-loaded, deliberately -- each sub-app's own code is no longer
// part of the initial bundle at all; the browser only downloads
// QueryPanel's own chunk, for instance, the moment someone actually
// navigates to /query, not on every page load regardless of which
// sub-app (if any) they end up using. This is the concrete, in-
// process realization of "the shell mounts/unmounts a sub-app," not
// a separate performance optimization bolted on afterward -- see
// Shell.tsx's own <Suspense> boundary around <Outlet />, which is
// what actually shows a loading state while a chunk is still in
// flight.
//
// LoginForm and Shell itself both stay eager, deliberately, not
// oversights: LoginForm is the very first meaningful content a
// logged-out person ever sees, and lazy-loading it would add a real
// network round-trip before anyone could even log in; Shell IS the
// persistent chrome itself, so lazy-loading it would mean the chrome
// flickers in too, defeating the entire point of "persistent."
//
// VisibleSchema imported separately, as a real, standalone `import
// type` -- lazy() itself only ever consumes a module's own default
// export at runtime (it awaits the dynamic import() and reads
// .default), so a type-only named export from that same module has
// to come through its own, ordinary static import instead; `import
// type` is fully erased at compile time (isolatedModules requires
// this to be unambiguous), so this adds no second network request
// and creates no eager reference to the module's own real code.
const QueryPanel = lazy(() => import('@elysium/app-query/QueryPanel'))
const ObjectSearchPanel = lazy(() => import('@elysium/app-browse/ObjectSearchPanel'))
const ObjectDetailPanel = lazy(() => import('@elysium/app-browse/ObjectDetailPanel'))
const AdminPanel = lazy(() => import('@elysium/app-admin/AdminPanel'))

type AuthStatus = 'checking' | 'loggedOut' | 'loggedIn'

// SECURITY, not just structure: the auth-gated render below is an
// EARLY RETURN, before <BrowserRouter>/<Routes> ever mounts -- not a
// wrapper rendered conditionally alongside them. This means that when
// not logged in, the route tree (including ObjectDetailPanel, which
// fetches real object data) genuinely does not exist in the component
// tree at all; there is no code path where a route's own render logic
// could run before an auth check does. UNCHANGED by the Shell
// redesign, and unchanged again by the httpOnly-cookie migration --
// this property was decided explicitly and deliberately preserved
// through both rewrites, not something to reconsider casually in a
// future edit.
//
// IMPORTANT, stated explicitly because it matters: this guard is
// client-side UX (don't attempt a doomed fetch, don't flash a broken
// page, redirect cleanly) -- it is NOT the real security boundary and
// must never be treated as one. The actual enforcement is, and must
// remain, server-side: every single API call requires a valid,
// non-expired session cookie verified by get_current_user() on EVERY
// request, completely independent of what this component does or
// doesn't check. Even a hypothetical bug in this guard could not
// itself leak real data -- the underlying fetch would still fail with
// a real 401. Don't let a future edit here start treating this as
// sufficient on its own.
//
// THREE real states now, not two -- authStatus is 'checking' |
// 'loggedOut' | 'loggedIn', not a plain isLoggedIn boolean. This is a
// REAL, necessary consequence of moving the session to an httponly
// cookie (see api.js's own header comment), not complexity added for
// its own sake: the old boolean could be computed SYNCHRONOUSLY, on
// first render, via `!!getToken()` against localStorage -- but
// JavaScript can never read an httponly cookie's own presence at all,
// by design. There is no synchronous check left to make; genuinely
// determining "is there already a valid session" now requires a real
// network round-trip, and this component must render SOMETHING while
// that's in flight, rather than incorrectly assume either logged-in
// or logged-out before the real answer comes back.
//
// A bookmarked, deep URL (e.g. /objects/Customer/cust_001) visited
// while logged out lands here first, on the FIRST render, before
// BrowserRouter ever reads the current location -- shows LoginForm
// correctly, not a flash of the route tree. Deliberately NOT
// preserving "return to where I was headed" after login (a real,
// separate UX enhancement, scoped out for this pass, not silently
// dropped) -- after logging in, the person lands on the default view,
// same as today.
export default function App() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>('checking')
  const [visibleSchema, setVisibleSchema] = useState<VisibleSchema | null>(null)
  const [visibleApps, setVisibleApps] = useState<VisibleApp[]>([])

  function handleLoginSuccess() {
    setAuthStatus('loggedIn')
  }

  async function handleLogout() {
    await logout()
    setAuthStatus('loggedOut')
    setVisibleSchema(null)
    setVisibleApps([])
  }

  function handleSessionExpired() {
    setAuthStatus('loggedOut')
    setVisibleSchema(null)
    setVisibleApps([])
  }

  // THE initial "is there already a valid session" check -- runs
  // ONCE, on mount, and ONLY decides authStatus itself; deliberately
  // does NOT also populate visibleSchema/visibleApps directly, even
  // though getMyVisibleSchema() below returns real, usable data on
  // success. See the two effects further down for why: each of THOSE
  // is gated on authStatus === 'loggedIn' and fires again on a FRESH
  // login too (handleLoginSuccess() above, a genuinely separate
  // moment this mount-only effect can't react to on its own) -- a
  // single, shared fetch here would correctly cover the "already
  // logged in when the page loaded" path but silently leave
  // visibleApps/visibleSchema empty forever after a fresh login,
  // since THIS effect never runs a second time. The accepted cost:
  // one real, deliberate, redundant fetch of each on the "already
  // logged in on page load" path specifically (this probe, then the
  // authStatus-gated effect firing right after) -- a cheap, self-
  // service call, not worth special-casing away at the cost of two
  // genuinely different code paths for what is otherwise the exact
  // same fetch.
  useEffect(() => {
    let cancelled = false
    async function checkSession() {
      try {
        await getMyVisibleSchema()
        if (!cancelled) setAuthStatus('loggedIn')
      } catch {
        // A 401 here is the NORMAL, expected "no session yet" case on
        // a fresh page load -- not a session that WAS valid and
        // stopped being so mid-use, so this deliberately does NOT go
        // through handleIfSessionExpired()/handleSessionExpired()
        // (those exist for that different case). Any OTHER error
        // (network failure, server unreachable) is treated
        // IDENTICALLY to "not logged in" here too -- fails closed,
        // never accidentally renders the route tree when this
        // genuinely can't confirm a real session exists.
        if (!cancelled) setAuthStatus('loggedOut')
      }
    }
    checkSession()
    return () => {
      cancelled = true
    }
  }, [])

  // Fetched on every transition INTO 'loggedIn' -- both the "already
  // logged in when the page first loaded" path (right after the probe
  // above) and a genuinely fresh login (handleLoginSuccess() above).
  // Passed down as a prop rather than independently re-fetched by
  // every view that needs it (ObjectSearchPanel and ObjectDetailPanel
  // both need to know which object types exist and which fields are
  // links). A React Context would be the OTHER reasonable way to
  // share this same value without prop drilling; deliberately not
  // used here since this app's component tree is still shallow and
  // flat (App -> a handful of sibling views, no real nesting) --
  // exactly the case Context is usually overkill for, not the deeply-
  // nested case it's meant to solve. Worth revisiting if the tree
  // ever grows deeper than that.
  useEffect(() => {
    if (authStatus !== 'loggedIn') return
    let cancelled = false
    async function loadSchema() {
      try {
        // getMyVisibleSchema() itself returns Promise<unknown> (see
        // api.ts's own header comment on why) -- asserted to the
        // real, known response shape here, matching api/routes.py's
        // own documented contract for GET /me/visible-schema.
        const schema = (await getMyVisibleSchema()) as VisibleSchema
        if (!cancelled) setVisibleSchema(schema)
      } catch (err) {
        handleIfSessionExpired(err, () => {
          if (!cancelled) handleSessionExpired()
        })
        // Any other error: leave visibleSchema null. Consuming views
        // (ObjectSearchPanel, ObjectDetailPanel) already handle a
        // null/not-yet-loaded schema as a loading state, not a crash.
      }
    }
    loadSchema()
    return () => {
      cancelled = true
    }
  }, [authStatus])

  // A SEPARATE, independent fetch/effect from visibleSchema above --
  // deliberately not combined into one Promise.all, even though both
  // run at the same moment: these are genuinely different concerns
  // (nav-level "which apps exist" vs. object-level "which types/
  // fields exist"), and keeping their own error handling isolated
  // matches how getMyVisibleSchema() was already its own independent
  // effect before this -- one more, similarly-independent effect is
  // consistent with that, not new complexity.
  useEffect(() => {
    if (authStatus !== 'loggedIn') return
    let cancelled = false
    async function loadApps() {
      try {
        // Same reasoning as loadSchema()'s own assertion above --
        // getVisibleApps() returns Promise<unknown>, asserted to the
        // real, known response shape matching GET /me/visible-apps.
        const apps = (await getVisibleApps()) as VisibleApp[]
        if (!cancelled) setVisibleApps(apps)
      } catch (err) {
        handleIfSessionExpired(err, () => {
          if (!cancelled) handleSessionExpired()
        })
        // Any other error: leave visibleApps as []. Shell already
        // renders an empty nav in that state, not a crash -- see its
        // own docstring for why that's the deliberate default, not a
        // gap.
      }
    }
    loadApps()
    return () => {
      cancelled = true
    }
  }, [authStatus])

  if (authStatus === 'checking') {
    // Brief, unavoidable moment while the real network round-trip
    // above is in flight -- see this file's own header comment for
    // why no synchronous check exists anymore. No spinner/skeleton
    // beyond plain text, matching every other data-fetching
    // component's own existing "Loading…" convention in this app.
    return (
      <div className="app">
        <header className="app__header">
          <h1>Elysium</h1>
        </header>
        <main>
          <p>Loading…</p>
        </main>
      </div>
    )
  }

  if (authStatus === 'loggedOut') {
    return (
      <div className="app">
        <header className="app__header">
          <h1>Elysium</h1>
        </header>
        <main>
          <LoginForm onSuccess={handleLoginSuccess} />
        </main>
      </div>
    )
  }

  // authStatus === 'loggedIn' from here on.
  //
  // Shell is now a real React Router LAYOUT route -- an element on
  // the wrapping <Route>, no path of its own -- not a plain component
  // this file renders directly around <Routes>. Every child route
  // below mounts INSIDE Shell's own <Outlet />, sharing its header/
  // nav automatically; Shell itself has no knowledge of which routes
  // exist, only of visibleApps (what to list in nav) and onLogout.
  // This IS the "outer app is a logical container, sub-apps are
  // functionality" boundary discussed and decided explicitly, made
  // real in code, not just true by convention: App.jsx owns identity/
  // fetching/routing wiring; Shell.jsx owns chrome; each routed panel
  // owns its own screen and nothing about any other route.
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Shell visibleApps={visibleApps} onLogout={handleLogout} />}>
          <Route path="/query" element={<QueryPanel onSessionExpired={handleSessionExpired} />} />
          <Route
            path="/browse"
            element={<ObjectSearchPanel visibleSchema={visibleSchema} onSessionExpired={handleSessionExpired} />}
          />
          <Route
            path="/objects/:objectType/:objectId"
            element={<ObjectDetailPanel visibleSchema={visibleSchema} onSessionExpired={handleSessionExpired} />}
          />
          <Route path="/admin" element={<AdminPanel onSessionExpired={handleSessionExpired} />} />
          <Route path="*" element={<Navigate to="/query" replace />} />
        </Route>
      </Routes>
    </BrowserRouter>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// CONTEXT: react-router-dom added here specifically because Stage 2
// (a real per-object Object View, see ObjectDetailPanel.jsx) needed a
// real, bookmarkable/shareable URL -- discussed and decided
// explicitly with the user before adding this dependency, not adopted
// speculatively. The security design of the auth guard below (an
// EARLY RETURN before BrowserRouter/Routes ever mounts, not a wrapper
// alongside them) was also discussed and decided explicitly -- see
// this file's own inline comment above App() for the full reasoning,
// including the explicit point that this guard is UX, not the real
// security boundary (server-side auth on every request is).
//
// RESOLVED (kept for history):
// - Sub-app routes (QueryPanel, ObjectSearchPanel, ObjectDetailPanel,
//   AdminPanel) are now lazy-loaded (React.lazy() + Shell.tsx's own
//   <Suspense> around <Outlet />) -- item #1 of the shell/launcher
//   upgrade plan. Confirmed with a real production build (separate,
//   real chunks per sub-app, main bundle shrank by the exact amount
//   that moved out) AND a live, real browser session against a real
//   running server: watched actual network requests and confirmed a
//   sub-app's own chunk loads only the first time someone navigates
//   there, the persistent chrome (header/nav) never disappears or
//   flickers during that load, and the newly-loaded screen renders
//   its own real content correctly -- not assumed correct from the
//   build output alone.
// - getMyVisibleSchema() lifted here from ObjectSearchPanel.jsx, once
//   ObjectDetailPanel.jsx needed the exact same value -- fetched
//   once, passed down as a prop to both. React Context was considered
//   as the alternative and explicitly deferred, not overlooked: this
//   app's tree is still shallow/flat (App -> a handful of sibling
//   views), the case Context is usually overkill for, not the deeply-
//   nested case it solves. Revisit if the tree ever grows deeper.
// - Every nav item is now a real react-router-dom <NavLink>, not a
//   setView() button -- Query/Browse/Admin all gained real,
//   independently bookmarkable URLs as a free side effect of adding
//   routing for Object View specifically, not a goal in themselves.
// - BREAKING REDESIGN, explicitly authorized: nav went from three
//   hardcoded <NavLink> entries (always shown to every logged-in
//   user, regardless of what they could actually use) to a real
//   React Router layout route (Shell.jsx) rendering nav from GET
//   /me/visible-apps. The user explicitly authorized breaking changes
//   to the UI for this -- "little to nothing important enough to
//   preserve" -- so this was a full rebuild of the nav/chrome
//   relationship, not an incremental patch. The security-critical
//   early-return guard above was explicitly, deliberately preserved
//   unchanged through this rewrite -- confirmed directly, not assumed
//   safe by proximity.
// - The session moved from a JS-readable localStorage token to a
//   real httponly cookie (core/auth/auth_cookies.py), closing a real,
//   found defense-in-depth gap a direct security review surfaced --
//   see that review's own findings. The genuine, necessary
//   consequence here: authStatus grew from a plain isLoggedIn boolean
//   to a real three-state 'checking' | 'loggedOut' | 'loggedIn',
//   since JavaScript can no longer synchronously read whether a
//   session already exists the way `!!getToken()` once could -- see
//   this file's own inline comment above App() for the full
//   reasoning, including the deliberate, accepted redundant fetch on
//   the "already logged in when the page loaded" path.
//
// DEFERRED (known, intentional, not yet built):
// - No "return to where I was headed" after being redirected to
//   login from a bookmarked deep URL -- a real, separate UX
//   enhancement, scoped out deliberately for this pass. After
//   logging in, the person lands on the default view (/query),
//   same as before routing existed at all.
// - visibleApps carries no icon/description -- deliberately minimal
//   (name + gating_permission + path only), chosen specifically to
//   keep debugging simple. Revisit if the nav ever needs richer
//   presentation than a plain text link.
