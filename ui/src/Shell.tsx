import { Suspense, useEffect, useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import UserMenu, { type CurrentUser } from '@elysium/shell-api/components/UserMenu'

// Shell.tsx  (the actual chrome -- a collapsible left sidebar, and
// the route tree's own mount point)
//
// Deliberately a SEPARATE file from App.jsx, not more logic folded
// into an already-large file. App.jsx's own job is auth state, what
// gets fetched once and passed down, and the top-level Routes wiring
// -- genuinely different concerns from "what does the persistent
// chrome actually render." Rendered as a real React Router LAYOUT
// route (an element with no path of its own, wrapping child routes
// via <Outlet />) -- not a plain component App.jsx calls directly --
// so every child route (Query, Browse, Admin, and eventually a real
// sub-app) mounts INSIDE this shell's own content pane, sharing the
// same sidebar without each route needing to render it itself.
//
// LEFT SIDEBAR, not the earlier top nav bar -- a deliberate structural
// match to a real, established reference (confirmed directly against
// that platform's own documentation, not assumed from memory): a
// persistent left sidebar that's the constant, home-base starting
// point for navigation, collapsible via an icon toggle and a keyboard
// shortcut, collapsed state remembered across visits. Taken at the
// right scale for what this app actually is, not copied at 1:1 scope
// -- that reference sidebar organizes a whole suite of workspaces
// into multiple named sections; this one organizes three sub-apps
// into a single flat list, which is all today's real visibleApps
// data supports or needs.
//
// Cmd/Ctrl+B, not Cmd/Ctrl+O -- the reference's own real shortcut is
// Cmd/Ctrl+O, but that combination is the browser's own native "Open
// File" shortcut in virtually every mainstream browser; fighting that
// is a real, avoidable rough edge. Cmd/Ctrl+B is the actual, common
// web-app convention for exactly this action (GitHub, VS Code,
// Notion, Linear all use it) -- same underlying goal, the genuinely
// idiomatic-for-the-web choice rather than a literal copy that
// collides with existing browser behavior.
//
// COLLAPSED MEANS FULLY HIDDEN, not shrunk to an icon strip -- the
// real reference's own collapsed state still shows one icon per
// section; visibleApps (GET /me/visible-apps) carries no icon data
// today, only path/name/gating_permission (see this file's own
// VisibleApp type below), and adding one would be a real backend and
// type change outside this specific step's own scope (a layout change
// only, no backend change -- decided explicitly before starting this
// file). A future icon-strip collapsed state is a real, deferred
// possibility once that data exists, not forgotten -- see the AI-only
// notes at the end of this file.
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
//
// <Suspense> wraps ONLY <Outlet />, not the sidebar -- App.tsx's own
// sub-app routes are lazy-loaded (see that file's own header
// comment), so the FIRST time someone navigates to a given sub-app,
// its code chunk is still in flight over the network for a brief
// moment. This boundary is what shows a loading state during that
// moment -- deliberately scoped to just the content pane, so the
// persistent sidebar stays fully rendered and interactive throughout;
// "persistent" would be a lie if the sidebar itself also disappeared
// behind the same fallback.

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
  currentUser: CurrentUser | null
  onLogout: () => void
}

const SIDEBAR_COLLAPSED_STORAGE_KEY = 'elysium.sidebarCollapsed'
// Below this width, default to collapsed on first load -- a real ~
// 15rem sidebar would swallow most of a real phone-sized viewport.
// A real, if basic, responsive floor -- see this project's own
// frontend-design skill's "responsive down to mobile" quality-floor
// requirement -- not a complete mobile redesign, which is real,
// separate, deferred work (see the AI-only notes at the end of this
// file). Kept in sync with index.css's own matching media query,
// which handles the ongoing, LIVE responsive behavior (the sidebar
// overlaying content instead of squeezing it on a narrow viewport)
// that this one-time, mount-only check can't -- this constant only
// ever decides the INITIAL default.
const MOBILE_BREAKPOINT_QUERY = '(max-width: 640px)'

// Read once, synchronously, as the real initial value -- not two
// renders (one wrong, then corrected) -- React's own lazy useState
// initializer form (a function, not a value) runs exactly once, on
// the very first render, before anything ever paints.
function getInitialCollapsedState(): boolean {
  try {
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY)
    if (stored !== null) return stored === 'true'
  } catch {
    // Private-browsing storage restrictions, a full quota, or a
    // disabled localStorage entirely -- all real, if rare, possible
    // failures. Falls through to the viewport-based default below
    // rather than ever letting a storage failure break the sidebar
    // itself from rendering at all.
  }
  return window.matchMedia(MOBILE_BREAKPOINT_QUERY).matches
}

export default function Shell({ visibleApps, currentUser, onLogout }: ShellProps) {
  const [collapsed, setCollapsed] = useState<boolean>(getInitialCollapsedState)

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next))
      } catch {
        // Same reasoning as getInitialCollapsedState() above -- a
        // failed WRITE must never break the toggle interaction
        // itself; the state still updates in memory for this
        // session, it just won't be remembered for the next one.
      }
      return next
    })
  }

  // Cmd/Ctrl+B toggles the sidebar from anywhere -- see this file's
  // own header comment for why this specific combination, not the
  // real reference's own Cmd/Ctrl+O. No guard against an input/
  // textarea currently having focus: every real browser and OS
  // already treats Cmd/Ctrl+<letter> as an application-level
  // shortcut, never literal text input, regardless of focus --
  // requiring the modifier key is what makes this safe.
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'b') {
        event.preventDefault()
        toggleCollapsed()
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  return (
    <div className={collapsed ? 'app app--sidebar-collapsed' : 'app'}>
      <aside className="app__sidebar" aria-hidden={collapsed}>
        <div className="app__sidebar-header">
          <h1>Elysium</h1>
        </div>
        <nav className="app__nav">
          {visibleApps.map((app) => (
            <NavLink key={app.path} to={app.path} className={({ isActive }) => (isActive ? '' : 'secondary')}>
              {app.name}
            </NavLink>
          ))}
        </nav>
        <UserMenu currentUser={currentUser} onLogout={onLogout} />
      </aside>

      <div className="app__content">
        {/* Lives in the content pane, not inside <aside>, deliberately
            -- when collapsed, the sidebar itself has zero width and
            nothing inside it is reachable at all, so the ONE control
            that can bring it back has to live somewhere that's always
            present regardless of collapsed state. */}
        <button
          type="button"
          className="app__sidebar-toggle"
          onClick={toggleCollapsed}
          aria-label={collapsed ? 'Show sidebar' : 'Hide sidebar'}
          aria-pressed={!collapsed}
          title={`${collapsed ? 'Show' : 'Hide'} sidebar (Ctrl+B or ⌘B)`}
        >
          <svg viewBox="0 0 20 20" width="20" height="20" fill="none" aria-hidden="true">
            <rect x="2.5" y="3.5" width="15" height="13" rx="2" stroke="currentColor" strokeWidth="1.4" />
            <line x1="7.5" y1="3.5" x2="7.5" y2="16.5" stroke="currentColor" strokeWidth="1.4" />
          </svg>
        </button>

        <main>
          <Suspense fallback={<p>Loading…</p>}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// CONTEXT: #2 of the shell/launcher upgrade plan (#1 was App.tsx's own
// lazy-loaded sub-app routes). Structural reference researched and
// confirmed directly against real platform documentation before
// building anything, not assumed from memory -- a persistent,
// collapsible left sidebar is that reference's own actual pattern,
// confirmed detail by detail (collapsed-by-default in the full
// platform, an icon-plus-keyboard-shortcut toggle, the sidebar
// described as the constant home-base for navigation). Explicitly
// NOT copied at that platform's own scale -- see this file's own
// header comment for the specific, deliberate departures (Cmd/Ctrl+B
// not Cmd/Ctrl+O, hidden-not-icon-strip collapse) and why each one is
// still faithful to the real underlying pattern, not a shortcut taken
// carelessly.
//
// RESOLVED (kept for history):
// - The bare "Log out" button became a real UserMenu dropdown (see
//   @elysium/shell-api/components/UserMenu) -- item #3 of the shell/
//   launcher upgrade plan. currentUser is fetched once in App.tsx
//   (GET /me) and passed down here, the same "fetched once, passed
//   down" pattern visibleApps/visibleSchema already established.
// - Defaults to OPEN on a normal desktop viewport, collapsed on a
//   narrow one -- decided explicitly: with only three real nav items
//   today, collapsed-by-default on desktop (matching the full
//   reference platform's own default) would hide almost the entire
//   sidebar's own value on first login, for a person who has no idea
//   yet that a toggle even exists. Worth revisiting once there are
//   enough sub-apps that an open-by-default sidebar meaningfully
//   competes with the content pane for room.
// - Two real, genuine bugs caught by LIVE browser verification
//   (Playwright, against a real running server), neither of which the
//   unit test suite could have caught on its own -- jsdom does not
//   apply real CSS at all, so a contrast/color regression is
//   structurally invisible to it:
//   1. App.tsx's own pre-login (checking/loggedOut) screens shared
//      the plain .app class with this file's own new sidebar layout;
//      once .app became a flex row for the sidebar, the login screen
//      itself would have rendered its header and content side-by-side
//      instead of stacked. Fixed by giving App.tsx's own pre-auth
//      screens a dedicated app__pre-auth class, entirely separate
//      from this file's own .app.
//   2. Leftover CSS rules from the OLD top-nav layout (a shared
//      `button, .app__nav a` rule, and `button.secondary, .app__nav
//      a.secondary`) were never removed when this file's own sidebar-
//      specific rules were added, and silently won via CSS
//      specificity -- the "Log out" button and any inactive nav link
//      rendered with dark, near-invisible text on this dark sidebar.
//      Fixed by fully decoupling .app__nav a into its own, complete,
//      self-contained rule, and giving Log out its own
//      .app__logout.secondary override with genuinely higher
//      specificity than the old global button.secondary rule (two
//      classes together beats element+class outright, regardless of
//      source order -- a plain, single-class .app__logout rule was
//      tried FIRST and confirmed, directly, to still lose).
//   Confirmed fixed via actual computed-style checks and screenshots
//   against a real, running page -- not re-inspected by eye alone,
//   and not assumed fixed just because the code read correctly.
//
// DEFERRED (known, intentional, not yet built):
// - No real icon-strip collapsed state -- see this file's own header
//   comment for why (no icon data on VisibleApp yet). If/when
//   visibleApps gains a real icon field, revisit collapsing to a
//   narrow icon strip instead of fully hiding the sidebar, closer to
//   the real reference's own collapsed state.
// - No live-resize handling -- getInitialCollapsedState() only ever
//   decides the sidebar's own state ONCE, at mount. Resizing an
//   existing, open session across the mobile breakpoint doesn't
//   retroactively collapse or reopen it. index.css's own media query
//   still keeps the sidebar from visually breaking layout at any
//   width regardless -- this is about the JS-driven default, not
//   visual correctness, and a real resize listener felt like more
//   complexity than this specific gap actually justified for a first
//   pass.
// - No full mobile redesign -- the sidebar-overlaying-content behavior
//   at a narrow viewport (see index.css) is the real, if basic,
//   quality floor this pass targets, not a complete, dedicated mobile
//   layout audit of every sub-app's own screen.
