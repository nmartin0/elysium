import { NavLink, Outlet } from 'react-router-dom'

// Shell.tsx  (the actual chrome -- header, data-driven nav, and the
// route tree's own mount point)
//
// Deliberately a SEPARATE file from App.jsx, not more logic folded
// into an already-large file. App.jsx's own job is auth state, what
// gets fetched once and passed down, and the top-level Routes wiring
// -- genuinely different concerns from "what does the persistent
// chrome actually render." Rendered as a real React Router LAYOUT
// route (an element with no path of its own, wrapping child routes
// via <Outlet />) -- not a plain component App.jsx calls directly --
// so every child route (Query, Browse, Admin, and eventually a real
// sub-app) mounts INSIDE this shell's own <main>, sharing the same
// header/nav without each route needing to render it itself.
//
// Nav is DATA-DRIVEN from visibleApps (GET /me/visible-apps) --
// replaces three hardcoded <NavLink> entries that were ALWAYS shown
// to every logged-in user regardless of what they could actually use
// (Admin was visible in nav even to a role with no manage:users grant
// at all -- every action inside it was already, separately, gated
// server-side; the button itself just never reflected that). Matches
// the exact same "never show something you can't actually use"
// discipline already applied to action buttons (see discover:
// action_types/"executable" on ObjectDetailPanel.jsx).
//
// visibleApps defaults to an empty array (see App.jsx) -- nav simply
// shows no links for the brief moment before the fetch resolves,
// rather than a flash of a hardcoded, possibly-wrong list. No loading
// spinner: this loads near-instantly in practice, and an empty nav
// for a split second is a safer default than showing something that
// might be about to disappear.

export interface VisibleApp {
  path: string
  name: string
  // Not read by this component at all -- included so the type stays
  // honest to the real GET /me/visible-apps response shape (see
  // api/routes.py), matching the same "don't invent a narrower type
  // than what the real object actually is" reasoning ActionForm.tsx's
  // own ActionDef already established. string | null, not required:
  // confirmed against this file's own real test data, which
  // deliberately includes it either way (null for an ungated app).
  gating_permission?: string | null
}

interface ShellProps {
  visibleApps: VisibleApp[]
  onLogout: () => void
}

export default function Shell({ visibleApps, onLogout }: ShellProps) {
  return (
    <div className="app">
      <header className="app__header">
        <h1>Elysium</h1>
        <nav className="app__nav">
          {visibleApps.map((app) => (
            <NavLink key={app.path} to={app.path} className={({ isActive }) => (isActive ? '' : 'secondary')}>
              {app.name}
            </NavLink>
          ))}
          <button className="secondary" onClick={onLogout}>
            Log out
          </button>
        </nav>
      </header>

      <main>
        <Outlet />
      </main>
    </div>
  )
}
