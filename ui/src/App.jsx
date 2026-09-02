import { useEffect, useState } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import LoginForm from '@elysium/shell-api/components/LoginForm'
import Shell from './Shell'
import QueryPanel from '@elysium/app-query/QueryPanel'
import ObjectSearchPanel from '@elysium/app-browse/ObjectSearchPanel'
import ObjectDetailPanel from '@elysium/app-browse/ObjectDetailPanel'
import AdminPanel from '@elysium/app-admin/AdminPanel'
import { getToken, logout, getMyVisibleSchema, getVisibleApps, handleIfSessionExpired } from '@elysium/shell-api/api'
import '@elysium/shell-api/index.css'

// SECURITY, not just structure: the `!isLoggedIn` check below is an
// EARLY RETURN, before <BrowserRouter>/<Routes> ever mounts -- not a
// wrapper rendered conditionally alongside them. This means that when
// logged out, the route tree (including ObjectDetailPanel, which
// fetches real object data) genuinely does not exist in the component
// tree at all; there is no code path where a route's own render logic
// could run before an auth check does. Reuses the EXACT isLoggedIn/
// onSessionExpired mechanism this app already had for its two
// original views, applied globally around the whole route tree now,
// rather than a second, new "guard component" concept that could
// drift out of sync with it -- fewer new code paths is itself a
// security property, not just simplicity for its own sake.
// UNCHANGED by the Shell redesign below -- this property was decided
// explicitly and deliberately preserved through the rewrite, not
// something to reconsider casually in a future edit.
//
// IMPORTANT, stated explicitly because it matters: this guard is
// client-side UX (don't attempt a doomed fetch, don't flash a broken
// page, redirect cleanly) -- it is NOT the real security boundary and
// must never be treated as one. The actual enforcement is, and must
// remain, server-side: every single API call requires a valid,
// non-expired token verified by get_current_user() on EVERY request,
// completely independent of what this component does or doesn't
// check. Even a hypothetical bug in this guard could not itself leak
// real data -- the underlying fetch would still fail with a real 401.
// Don't let a future edit here start treating this as sufficient on
// its own.
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
  const [isLoggedIn, setIsLoggedIn] = useState(!!getToken())
  const [visibleSchema, setVisibleSchema] = useState(null)
  const [visibleApps, setVisibleApps] = useState([])

  function handleLoginSuccess() {
    setIsLoggedIn(true)
  }

  async function handleLogout() {
    await logout()
    setIsLoggedIn(false)
    setVisibleSchema(null)
    setVisibleApps([])
  }

  function handleSessionExpired() {
    setIsLoggedIn(false)
    setVisibleSchema(null)
    setVisibleApps([])
  }

  // Fetched ONCE, here, and passed down -- not independently re-
  // fetched by every view that needs it (ObjectSearchPanel and
  // ObjectDetailPanel both need to know which object types exist and
  // which fields are links). A React Context would be the OTHER
  // reasonable way to share this same value without prop drilling;
  // deliberately not used here since this app's component tree is
  // still shallow and flat (App -> a handful of sibling views, no
  // real nesting) -- exactly the case Context is usually overkill for,
  // not the deeply-nested case it's meant to solve. Worth revisiting
  // if the tree ever grows deeper than that.
  useEffect(() => {
    if (!isLoggedIn) return
    let cancelled = false
    async function loadSchema() {
      try {
        const schema = await getMyVisibleSchema()
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
  }, [isLoggedIn])

  // A SEPARATE, independent fetch/effect from visibleSchema above --
  // deliberately not combined into one Promise.all, even though both
  // run at the same moment: these are genuinely different concerns
  // (nav-level "which apps exist" vs. object-level "which types/
  // fields exist"), and keeping their own error handling isolated
  // matches how getMyVisibleSchema() was already its own independent
  // effect before this -- one more, similarly-independent effect is
  // consistent with that, not new complexity.
  useEffect(() => {
    if (!isLoggedIn) return
    let cancelled = false
    async function loadApps() {
      try {
        const apps = await getVisibleApps()
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
  }, [isLoggedIn])

  if (!isLoggedIn) {
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
