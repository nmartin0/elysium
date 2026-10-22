import { useEffect, useState } from 'react'
import { Button, Classes } from '@blueprintjs/core'
import { useLocation, useNavigate } from 'react-router-dom'
import { Frame } from '@shell/core/Frame'
import type { Command } from '@shell/core/commands'
import { iconForApp } from '@elysium/shell-api/appIcons'
import { readPreference, writePreference } from '@elysium/shell-api/browserPreferences'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import UserMenu, { type CurrentUser } from '@elysium/shell-api/components/UserMenu'
import { DENSITIES, type Density, isDensity } from '@elysium/shell-api/density'
import { getSavedViews, getVisibleActionTypesCached } from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'
import {
  actionCommands,
  objectInScope,
  type PaletteAction,
  type PaletteView,
  searchSuggestions,
  typeCommands,
  viewCommands,
} from './paletteCommands'
import { totalWaiting, useInboxCounts } from '@elysium/shell-api/useInboxCounts'
import HelpPanel from '@elysium/shell-api/components/HelpPanel'

// Shell.tsx -- ELYSIUM'S COMPOSITION OF THE GENERIC FRAME.
//
// The rail, the header and the command palette are the shell's
// (@shell/core/Frame, BLOCKING.md item 3, step 1.3): it draws them and
// owns how they behave -- collapsing, the narrow-screen rules, Ctrl+B,
// Cmd-K, the navigation commands. This file supplies what is Elysium's:
// the product's name, the header's actions (the Inbox, help, the theme,
// the user menu), the theme and row density themselves, and the palette
// commands that know Elysium's data.
//
// TWO OF THOSE ARE THE VIOLATIONS STEP 1.3 REMOVES, and are here only
// until then: Browse's commands (types, saved views, actions, searches)
// become Browse's own declared commands, which also ends the frame being
// handed the schema; and the Inbox's count becomes a badge on its rail
// entry.

export interface VisibleApp {
  path: string
  name: string
  /** What a person is working on; the rail groups by it (FrameNavEntry). */
  subject?: string
}

interface ShellProps {
  visibleApps: VisibleApp[]
  /** For the palette's types and searches; null until it arrives, and
   * the palette simply has fewer commands until then. */
  visibleSchema?: VisibleSchema | null
  currentUser: CurrentUser | null
  onLogout: () => void
}

/** Kept from before the frame moved, so a browser's remembered rail
 *  state survives the move. */
const SIDEBAR_COLLAPSED_STORAGE_KEY = 'elysium.sidebarCollapsed'

export default function Shell({ visibleApps, visibleSchema = null, currentUser, onLogout }: ShellProps) {
  const location = useLocation()
  const navigate = useNavigate()
  // THE HELP ASSISTANT, and which screen it is being asked from -- the
  // rail's own name for it, so "how do I filter this" has a referent.
  const [helpOpen, setHelpOpen] = useState(false)
  const currentScreen = visibleApps.find((app) => location.pathname.startsWith(app.path))?.name ?? null

  /**
   * WHAT THE PALETTE FETCHES, AND WHEN: the reader's saved views and the
   * action types, each time it OPENS -- not per keystroke, and not on
   * every page load for a palette most loads never open. The list it
   * filters is in memory by the time anyone types (DEV_UI 10.1: "opens
   * in under 100ms or it will not be used"); a view saved a minute ago
   * is there next time it opens.
   *
   * A FAILURE IS FEWER COMMANDS, not an error in the palette: navigation
   * and types still work, and a session that has expired is noticed by
   * whatever the page itself asks next.
   */
  const [paletteViews, setPaletteViews] = useState<PaletteView[]>([])
  const [paletteActions, setPaletteActions] = useState<Record<string, PaletteAction> | null>(null)
  const loadPaletteData = () => {
    void (async () => {
      try {
        setPaletteViews(await getSavedViews())
      } catch {
        setPaletteViews([])
      }
    })()
    void (async () => {
      try {
        setPaletteActions((await getVisibleActionTypesCached()) as Record<string, PaletteAction>)
      } catch {
        setPaletteActions(null)
      }
    })()
  }

  const canBrowse = visibleApps.some((app) => app.path === '/browse')
  const scope = objectInScope(location.pathname)
  const browsingType = location.pathname.startsWith('/browse')
    ? new URLSearchParams(location.search).get('type')
    : (scope?.type ?? null)
  /**
   * Dark mode, which Blueprint provides per widget and nothing turned
   * on. Applied as a class on <body> rather than a parallel
   * stylesheet: every Blueprint component already carries its own dark
   * variant, and tokens.css redefines its surface variables under the
   * same selector.
   *
   * Kept in browser storage per user, since a theme is a preference
   * and re-choosing it every visit is the kind of small friction that
   * makes an app feel unfinished.
   *
   * DARK BY DEFAULT (DEV_UI 8.6.6, confirmed by the owner 14 Oct), and
   * a CHOICE is remembered only when somebody makes one. The old key,
   * `theme`, was written on every render -- so every browser that ever
   * opened Elysium held "light" without anyone choosing it, and a new
   * default could never have reached them. `theme-choice` is written
   * by the toggle alone; the old key is read by nothing.
   */
  //
  // READ EVERY RENDER, NOT ONCE. The shell can mount before the user is
  // known -- a reload renders it while /me is still answering -- and a
  // value read once at mount was read under nobody's name, so a choice
  // of light came back dark on every reload (seen in a real browser).
  // A localStorage read is microseconds; the state below only holds a
  // choice made in this session, for the user who made it.
  const username = currentUser?.username ?? ''
  const [chosen, setChosen] = useState<{ username: string; dark: boolean } | null>(null)
  const dark =
    chosen !== null && chosen.username === username
      ? chosen.dark
      : readPreference<string>('theme-choice', username, 'dark') === 'dark'
  const chooseTheme = (nextDark: boolean) => {
    setChosen({ username, dark: nextDark })
    writePreference('theme-choice', username, nextDark ? 'dark' : 'light')
  }

  // ROW DENSITY (DEV_UI 9.3), the same shape as the theme: the reader's,
  // remembered per user, middle until they choose. Applied as
  // data-density on <body>, which every DataTable's row height reads.
  const [chosenDensity, setChosenDensity] = useState<{ username: string; density: Density } | null>(null)
  const storedDensity = readPreference<string>('density', username, 'middle')
  const density: Density =
    chosenDensity !== null && chosenDensity.username === username
      ? chosenDensity.density
      : isDensity(storedDensity)
        ? storedDensity
        : 'middle'
  const chooseDensity = (next: Density) => {
    setChosenDensity({ username, density: next })
    writePreference('density', username, next)
  }

  /**
   * THE PALETTE'S WHOLE LIST, in the order a person reaches for it:
   * actions on what is in front of them, then places (the frame's own
   * navigation commands), types and their own views, then settings. Rebuilt per render -- a
   * few dozen objects -- because half of it depends on the location.
   *
   * THE SAME LABELS AS THE BUTTONS (DEV_UI 10.4): "Help", "Log out",
   * "Switch to light theme" -- somebody who learnt the button finds the
   * command by the word they already know.
   */
  const go = (to: string) => void navigate(to)
  const settingsCommands: Command[] = [
    { id: 'shell:help', label: 'Help', group: 'Shell', run: () => setHelpOpen(true) },
    {
      id: 'shell:theme',
      label: dark ? 'Switch to light theme' : 'Switch to dark theme',
      group: 'Shell',
      run: () => chooseTheme(!dark),
    },
    ...DENSITIES.filter((choice) => choice.value !== density).map((choice) => ({
      id: `shell:density:${choice.value}`,
      label: `Row density: ${choice.label}`,
      group: 'Shell',
      run: () => chooseDensity(choice.value),
    })),
    { id: 'shell:logout', label: 'Log out', group: 'Shell', run: onLogout },
  ]
  const commands = {
    before: actionCommands(scope, paletteActions, go),
    after: [
      ...(canBrowse ? typeCommands(visibleSchema, go) : []),
      ...(canBrowse ? viewCommands(paletteViews, go) : []),
      ...settingsCommands,
    ],
  }
  const suggest = (query: string) => (canBrowse ? searchSuggestions(query, visibleSchema, browsingType, go) : [])

  useEffect(() => {
    document.body.dataset.density = density
  }, [density])

  useEffect(() => {
    // Classes.DARK, not a literal. Blueprint 6 emits `bp6-dark` and
    // 5 emitted `bp5-dark`; a hardcoded string silently stops working
    // on a major upgrade, and the test asserting the same literal
    // would keep passing -- which is exactly what happened here.
    document.body.classList.toggle(Classes.DARK, dark)
  }, [dark])

  const inboxCounts = useInboxCounts(location.pathname + location.search)
  const waiting = totalWaiting(inboxCounts)

  return (
    <Frame
      nav={visibleApps.map((app) => ({ title: app.name, path: app.path, subject: app.subject }))}
      brand="Elysium"
      iconFor={iconForApp}
      actions={
        <>
          {/* THE INBOX, PRESENT WITHOUT PROMPTING (DEV_UI 15.3): a number
        on every screen and nothing that pops up. Decisions and
        unread notices together; the Inbox's tabs say which. */}
          <Button
            minimal
            icon="inbox"
            className="app__inbox"
            aria-label={waiting > 0 ? `Inbox, ${waiting} waiting` : 'Inbox'}
            onClick={() => navigate('/inbox')}
          >
            {waiting > 0 && <span className="app__inbox-count">{waiting > 99 ? '99+' : waiting}</span>}
          </Button>
          <Button minimal icon="help" aria-label="Help" onClick={() => setHelpOpen(true)} />
          <Button
            minimal
            icon={dark ? 'flash' : 'moon'}
            aria-label={dark ? 'Switch to light theme' : 'Switch to dark theme'}
            onClick={() => chooseTheme(!dark)}
          />
          <UserMenu currentUser={currentUser} onLogout={onLogout} density={density} onDensity={chooseDensity} />
        </>
      }
      overlays={<HelpPanel isOpen={helpOpen} onClose={() => setHelpOpen(false)} screen={currentScreen} />}
      commands={commands}
      suggest={suggest}
      onPaletteOpen={loadPaletteData}
      fallback={<LoadingState />}
      storageKey={SIDEBAR_COLLAPSED_STORAGE_KEY}
    />
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. MOSTLY THE HISTORY OF THE FRAME, which
// now lives in @shell/core/Frame.tsx (step 1.3); kept because the reasons
// it records still hold there. Context for a future AI session (or me,
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
// - `gating_permission` removed from the VisibleApp interface --
//   part of a real, third security fix (see api/routes.py's own
//   AI-notes for the full story): confirmed by a direct grep that
//   this field was never actually read anywhere on the frontend,
//   only declared in this type "to stay honest to the real API
//   response shape" -- but that response shape itself was the real
//   bug (an internal permission-string name leaking to the browser
//   unfiltered), now fixed at the route layer. This type updated to
//   match, staying honest to the NEW real shape instead.
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
// - A real, deliberate REVISION of this file's own earlier, explicit
//   decision to do nothing special on the reverse transition (mobile
//   back to desktop) -- made directly in response to real, live
//   testing, not a quietly-corrected oversight: resizing down into
//   mobile (correctly auto-closing, per the entry above) and then
//   immediately back up left the sidebar hidden until a separate,
//   manual tap, even though the person never took any action of their
//   own to close it -- reported directly as genuinely surprising, not
//   assumed to be a real problem in advance. Fixed by restoring the
//   real, persisted desktop preference (via
//   resolveCollapsedFromStorageOrViewport(), the same function the
//   initial mount already uses, called a second time here rather than
//   duplicated) the moment isMobile transitions back to false --
//   possible specifically because the entering-mobile force-close
//   deliberately never touches storage, so the real, original
//   preference is always still sitting there to restore. getInitial-
//   CollapsedState() renamed to resolveCollapsedFromStorageOrViewport()
//   as part of this same change, reflecting its now-genuine dual use,
//   not just the one-time "initial" read its old name implied. Two
//   new, dedicated tests confirm this precisely: one starting from a
//   genuinely open desktop preference (restores to open, matching the
//   real report), one starting from a genuinely, deliberately closed
//   one (stays closed) -- confirming this restores the real, persisted
//   choice, not just "always reopens." Both confirmed live in a real
//   browser too, reproducing the exact reported resize-down-then-up
//   sequence end to end.
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
