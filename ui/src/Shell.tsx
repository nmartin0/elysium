import { Suspense, useEffect, useRef, useState, useSyncExternalStore } from 'react'
import { Outlet, useLocation, useNavigate } from 'react-router-dom'
import { Drawer, Menu, MenuItem } from '@blueprintjs/core'
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
// file). This same query now drives TWO real, live things below, not
// just the one-time initial default it originally only decided:
// getInitialCollapsedState()'s own initial read, AND isMobile's own
// real, live matchMedia listener, which is what decides whether
// Drawer or the plain <aside> actually renders, kept current for the
// whole session, not just at mount.
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

// subscribeToMobileBreakpoint/getIsMobileSnapshot -- module-level, not
// defined inside the component, deliberately: useSyncExternalStore's
// own real contract is that a NEW subscribe function identity on every
// render causes React to unsubscribe and resubscribe on every single
// render (confirmed directly against React's own docs), which would
// mean creating and tearing down a real MediaQueryList and event
// listener on every render -- wasteful, not just inelegant. Module-
// level functions have a permanently stable identity across the whole
// app's lifetime, avoiding that entirely.
//
// useSyncExternalStore, not useState+useEffect -- the real, current
// React-recommended pattern specifically for subscribing to a value
// that lives OUTSIDE React and can change on its own (confirmed
// directly against React's own docs and a real, matching example
// using this exact matchMedia use case) -- window.matchMedia is
// exactly that: a real, external, mutable data source, not React
// state. useSyncExternalStore is what guarantees a consistent value
// is read even under concurrent rendering (the "tearing" problem a
// plain useEffect-based subscription does not protect against), and
// replaces what used to be a separate useState PLUS a separate
// useEffect with one, more correct hook call.
//
// No getServerSnapshot (the third, optional argument) -- confirmed
// directly this is genuinely optional for a fully client-rendered app
// with no SSR at all, which this project is (a plain Vite + React SPA,
// bootstrapped client-side in main.tsx) -- there is no server render
// to reconcile against.
function subscribeToMobileBreakpoint(onChange: () => void): () => void {
  const mediaQueryList = window.matchMedia(MOBILE_BREAKPOINT_QUERY)
  mediaQueryList.addEventListener('change', onChange)
  return () => mediaQueryList.removeEventListener('change', onChange)
}

function getIsMobileSnapshot(): boolean {
  return window.matchMedia(MOBILE_BREAKPOINT_QUERY).matches
}

export default function Shell({ visibleApps, currentUser, onLogout }: ShellProps) {
  const [collapsed, setCollapsed] = useState<boolean>(getInitialCollapsedState)
  // useSyncExternalStore, not useState+useEffect -- see
  // subscribeToMobileBreakpoint/getIsMobileSnapshot's own header
  // comment above for the full reasoning. This one hook call replaces
  // what used to be a separate useState (for the initial read) plus a
  // separate useEffect (for the live subscription).
  const isMobile = useSyncExternalStore(subscribeToMobileBreakpoint, getIsMobileSnapshot)
  const location = useLocation()
  const navigate = useNavigate()

  // Persists to localStorage -- the one real, shared implementation
  // both the desktop toggle and the mobile Drawer's own dismissal
  // (backdrop click, Escape, a real nav-triggered auto-close below)
  // all go through, so "the sidebar's own remembered state" means the
  // same thing regardless of which of those actually changed it.
  //
  // Takes a plain boolean, not a computed toggle -- every real caller
  // (onClose, the auto-close-on-navigate effect below) always wants
  // ONE fixed, known target value, never "whatever it currently
  // isn't." That distinction matters: toggleCollapsed() below is the
  // ONE caller that used to compute its own next value this way
  // (`setCollapsedPersisted(!collapsed)`), and that specific pattern
  // is what caused a real, confirmed bug -- see toggleCollapsed()'s
  // own comment.
  function setCollapsedPersisted(next: boolean) {
    setCollapsed(next)
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next))
    } catch {
      // Same reasoning as getInitialCollapsedState() above -- a
      // failed WRITE must never break the interaction itself; the
      // state still updates in memory for this session, it just
      // won't be remembered for the next one.
    }
  }

  // A real, severe, previously-shipped bug, found and fixed here, not
  // assumed correct just because a single press worked in existing
  // tests -- confirmed directly with a real, repeated-press
  // reproduction before writing this fix, not reasoned about in the
  // abstract: this used to read `setCollapsedPersisted(!collapsed)`,
  // computing the next value from `collapsed` captured in this
  // render's own closure. That closure can be genuinely stale for two
  // real, independent reasons -- either is enough on its own: (1) the
  // keydown listener below is registered via a useEffect with an
  // EMPTY dependency array, so it only ever closes over the
  // toggleCollapsed from the very first render, forever, and (2) even
  // ignoring that, two rapid, back-to-back calls within the same
  // React batch both read the SAME pre-update `collapsed` value,
  // since neither call has actually re-rendered yet when the second
  // one fires. Confirmed directly, with real fireEvent presses, not
  // hypothetically: three separate, discrete Cmd+B presses in a real
  // test produced true -> false -> false -> false (should alternate
  // true/false/true/false) -- the shortcut only ever worked once, then
  // got permanently stuck, silently, since mount.
  //
  // Fixed with React's own functional updater form of setState, which
  // is specifically designed to guarantee the true, latest queued
  // state regardless of which render's closure a given call happens
  // to have been made from -- this is what actually, robustly fixes
  // the bug, not a change to the keydown effect's own dependency array
  // (which would only address cause (1) above, not (2); this fixes
  // both at the true source). localStorage's own write lives inside
  // this same updater, deliberately -- it needs the real, resolved
  // next value, which only exists inside the updater itself, not in
  // this function's own outer scope. React 18 Strict Mode invokes
  // updater functions twice in development specifically to surface
  // impurities; writing the same, idempotent value to localStorage
  // twice is harmless (identical end state), not a correctness bug --
  // this is the same accepted pattern widely-used localStorage-backed
  // toggle hooks already rely on.
  function toggleCollapsed() {
    setCollapsed((prevCollapsed) => {
      const next = !prevCollapsed
      try {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next))
      } catch {
        // Same reasoning as getInitialCollapsedState() above.
      }
      return next
    })
  }

  // Forces the sidebar CLOSED specifically when a live resize crosses
  // INTO mobile, deliberately -- a real, genuine UX gap this file's
  // own live testing surfaced directly, not something caught in
  // advance: without this, resizing a desktop session (open by
  // default) down into mobile width carried that same "open" state
  // straight into the real Drawer, which meant its own real backdrop
  // appeared and dimmed the whole screen from nothing more than a
  // resize -- no deliberate tap from the person at all. That's a
  // genuinely different, lesser-consent action than actually choosing
  // to open the sidebar, and it broke the same "closed by default,
  // deliberately opened" pattern already governing both the initial
  // mobile default (getInitialCollapsedState()) and the auto-close-
  // on-navigate effect below. Fixed to match those, not left as its
  // own, inconsistent third rule.
  //
  // setCollapsed, NOT setCollapsedPersisted -- deliberately does not
  // write to localStorage. This is a real, viewport-driven default,
  // not a deliberate choice the person actually made; persisting it
  // would silently overwrite a real, separate desktop preference the
  // next time this same browser loads at a normal width, for a resize
  // that may have had nothing to do with any real intent about the
  // sidebar at all.
  //
  // Deliberately does NOT do anything special on the reverse
  // transition (mobile back to desktop) -- collapsed simply stays
  // whatever it already was (closed, from entering mobile, unless the
  // person explicitly reopened it while still on mobile), and the
  // container swaps back to the in-flow <aside>. A person can reopen
  // it with one tap either way; a second, separate rule for the
  // reverse direction wasn't asked for and isn't obviously more
  // correct than this, simpler default.
  //
  // Reacts to a genuine TRANSITION into mobile (false -> true), not
  // merely "isMobile is currently true" -- wasNotMobileRef holds the
  // previous render's own isMobile value, read (and then updated)
  // inside the effect itself. On the very first render, the ref's own
  // initializer captures whatever isMobile already was at that exact
  // moment, so the very first effect run always computes
  // wasNotMobile = !isMobile -- meaning the `isMobile && wasNotMobile`
  // condition below can never be true on mount, regardless of whether
  // isMobile starts true or false. That's deliberate, not incidental:
  // the initial mount-time state is getInitialCollapsedState()'s own,
  // separate, already-correct responsibility; this effect must only
  // ever react to a REAL, later change, the same real distinction the
  // auto-close-on-navigate effect below also has to make, just via a
  // different mechanism (that one guards the first run explicitly,
  // this one derives it from comparing against a genuine previous
  // value instead).
  const wasNotMobileRef = useRef(!isMobile)
  useEffect(() => {
    const wasNotMobile = wasNotMobileRef.current
    wasNotMobileRef.current = !isMobile
    if (isMobile && wasNotMobile) {
      setCollapsed(true)
    }
  }, [isMobile])

  // Auto-closes the mobile Drawer on navigation -- a real, genuine UX
  // gap CONFIRMED to already exist even before this file touched
  // Drawer at all (live-verified against the prior, CSS-only mobile
  // overlay: tapping a nav link left the sidebar open, still covering
  // the newly-navigated screen, requiring a separate, manual tap to
  // dismiss) -- fixing this here, not just matching what was already
  // there.
  //
  // Depends on [location.pathname] ONLY, deliberately -- reads the
  // latest isMobile/collapsed via a ref, not as effect dependencies.
  // Including collapsed itself as a dependency would be a genuine bug,
  // not just unnecessary: OPENING the drawer changes collapsed, which
  // would immediately re-run this exact effect and re-close it before
  // it could ever be seen open at all. This must react ONLY to a real
  // path change, reading whatever isMobile/collapsed happen to be at
  // that moment -- not re-run every time either of them changes for
  // some unrelated reason.
  //
  // isFirstRunRef guards against a second, real, CONFIRMED bug, not a
  // precaution taken on principle -- an effect keyed on
  // [location.pathname] still runs once on the very first mount, not
  // only on a genuine, later navigation. Without this guard, a stored
  // "false" (explicitly OPEN) preference on a narrow viewport was
  // immediately, incorrectly collapsed again the instant the page
  // loaded -- caught directly by this file's own "a stored false
  // preference overrides matchMedia" test, which failed with exactly
  // that symptom before this guard existed, not reasoned about
  // in the abstract.
  const isFirstRunRef = useRef(true)
  const latestStateRef = useRef({ isMobile, collapsed })
  latestStateRef.current = { isMobile, collapsed }
  useEffect(() => {
    if (isFirstRunRef.current) {
      isFirstRunRef.current = false
      return
    }
    const { isMobile: currentlyMobile, collapsed: currentlyCollapsed } = latestStateRef.current
    if (currentlyMobile && !currentlyCollapsed) {
      setCollapsedPersisted(true)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname])

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

  // Menu/MenuItem, not NavLink -- Blueprint's own real vocabulary for
  // exactly this ("side navigation" isn't a distinct Blueprint
  // component; a vertically-stacked Menu inside your own layout
  // container IS the real, confirmed pattern -- Navbar has been a
  // real, open Blueprint feature request for vertical orientation
  // since 2016, never implemented). MenuItem has no router-aware
  // "render as" mechanism of its own (confirmed directly, not
  // assumed), so this uses the same real, standard pattern any
  // non-router-aware link-like component needs (confirmed against a
  // real, working MUI example doing the same integration): a real
  // href for genuine semantics (right-click "open in new tab" etc.
  // still works correctly), but the actual click is intercepted --
  // preventDefault() stops MenuItem's own plain <a> from doing a full
  // page reload, and react-router-dom's own navigate() does the real,
  // client-side transition instead. active is computed by hand from
  // useLocation(), since MenuItem has no idea routing exists at all.
  const navItems = visibleApps.map((app) => (
    <MenuItem
      key={app.path}
      text={app.name}
      href={app.path}
      active={location.pathname === app.path}
      onClick={(event) => {
        event.preventDefault()
        navigate(app.path)
      }}
    />
  ))

  // The same real content, either way -- only the CONTAINER differs
  // between mobile and desktop (see this file's own AI-notes for why:
  // Drawer is architecturally right for mobile's own transient,
  // overlay-on-top-of-content behavior; it is NOT right for desktop's
  // permanent, in-flow sidebar, which stays this file's own <aside>).
  const sidebarContent = (
    <>
      <div className="app__sidebar-header">
        <h1>Elysium</h1>
      </div>
      <Menu className="app__nav">{navItems}</Menu>
      <UserMenu currentUser={currentUser} onLogout={onLogout} />
    </>
  )

  return (
    <div className={collapsed ? 'app app--sidebar-collapsed' : 'app'}>
      {isMobile ? (
        // Real Drawer here, not the old CSS-only position: fixed
        // overlay -- genuinely, architecturally the right fit
        // (confirmed directly against this project's own earlier
        // planning: the prior mobile behavior -- position: fixed,
        // overlaying content, a real box-shadow -- already matched
        // Drawer's own real design intent, unlike the permanent
        // desktop sidebar, which does not). onClose fires on every
        // real Blueprint-provided dismissal (backdrop click, Escape)
        // -- all routed through the same setCollapsedPersisted() the
        // toggle button and nav-triggered auto-close above also use,
        // so "the sidebar's own remembered state" means one consistent
        // thing regardless of which of those actually changed it.
        <Drawer
          isOpen={!collapsed}
          position="left"
          size="15rem"
          onClose={() => setCollapsedPersisted(true)}
          className="app__sidebar"
        >
          {sidebarContent}
        </Drawer>
      ) : (
        <aside className="app__sidebar" aria-hidden={collapsed}>
          {sidebarContent}
        </aside>
      )}

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
// - Blueprint's own sidebar migration (see feature/blueprint-migration):
//   nav rebuilt on Menu/MenuItem, UserMenu rebuilt on PopoverNext --
//   but Collapse (Blueprint's expand/collapse primitive) deliberately
//   NOT used for the sidebar's own width animation. Confirmed directly
//   against Blueprint's own docs before considering it, not assumed:
//   Collapse animates HEIGHT only ("calculates height to animate the
//   transition," explicitly warns against position: absolute content)
//   -- built for vertical accordion-style content, not this sidebar's
//   horizontal collapse. A genuine, honest mismatch, not a gap to
//   force-fill; the width animation stays this file's own CSS,
//   correctly outside Blueprint's real scope.
//   While reviewing that exact CSS, found and fixed a real, separate,
//   PRE-EXISTING bug, unrelated to Blueprint: .app__sidebar's own
//   `transition: margin-left 0.15s ease` transitioned a property the
//   collapsed state never actually changes (it changes width,
//   padding-left, padding-right instead) -- confirmed empirically, not
//   just by reading the CSS: sampled the sidebar's real width 6 times
//   across ~180ms after a real collapse click, before the fix, and it
//   was 0 on every sample -- an instant snap, not the smooth animation
//   the declaration looked like it should produce. Fixed by
//   transitioning the actual properties that change; confirmed after
//   the fix with the same real sampling technique, both directions
//   (collapse: 240 -> 212.9 -> 101.7 -> 35.4 -> 7.3 -> 0; expand: 0 ->
//   27.0 -> 138.2 -> 204.5 -> 232.7 -> 240 -- genuinely smooth now).
// - The mobile Drawer, replacing the old CSS-only position: fixed
//   overlay -- genuinely, architecturally right for mobile specifically
//   (confirmed via this same migration's own earlier planning: the
//   prior mobile behavior already matched Drawer's own real design
//   intent -- overlay-on-top-of-content, a real box-shadow -- unlike
//   the permanent desktop sidebar, which correctly stays this file's
//   own <aside>, never Drawer). This is also what closes the "no
//   live-resize handling" gap this file's own notes previously,
//   honestly, deferred -- isMobile is now a real, LIVE matchMedia
//   listener (addEventListener('change', ...)), confirmed working in a
//   real browser, not just the mocked test environment: resized an
//   already-loaded desktop session down to a real mobile viewport and
//   watched it switch to the real Drawer, backdrop and all, with no
//   reload.
//   A real, PRE-EXISTING UX gap found and fixed along the way, not
//   just matched: live-verified, before writing any Drawer code, that
//   the OLD CSS-only mobile overlay never auto-closed on navigation --
//   tapping a nav link left the sidebar open, still covering the
//   newly-navigated screen. Fixed here (auto-closes on a real,
//   subsequent path change) rather than carried forward into the new
//   implementation unexamined.
//   A real bug in that auto-close effect, found by its own test suite,
//   not shipped unnoticed: an effect keyed on [location.pathname]
//   still runs once on the very first mount, not only on a genuine
//   later navigation -- without a first-run guard, a stored, explicitly
//   OPEN mobile preference was incorrectly re-collapsed the instant the
//   page loaded. Confirmed via a real negative control: reverting the
//   guard reproduced exactly one, correct test failure, not a vague
//   "something's wrong."
//   A real, second lesson (beyond UserMenu's own PopoverNext one) in
//   Blueprint's real, empirical event/timing behavior, not assumed:
//   Drawer's own backdrop dismissal responds to mousedown, not click
//   -- confirmed directly (a real fireEvent.click() on the backdrop
//   never triggered onClose at all, even after a full waitFor
//   timeout), the same real pattern UserMenu's own hand-rolled click-
//   outside detection already used for the same underlying reason.
//
// DEFERRED (known, intentional, not yet built):
// - No real icon-strip collapsed state -- see this file's own header
//   comment for why (no icon data on VisibleApp yet). If/when
//   visibleApps gains a real icon field, revisit collapsing to a
//   narrow icon strip instead of fully hiding the sidebar, closer to
//   the real reference's own collapsed state.
// - No full mobile redesign -- the sidebar-overlaying-content behavior
//   at a narrow viewport (now the real Drawer, see this file's own
//   RESOLVED note above) is the real, if basic, quality floor this
//   pass targets, not a complete, dedicated mobile layout audit of
//   every sub-app's own screen.
