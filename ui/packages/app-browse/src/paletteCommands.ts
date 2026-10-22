/**
 * WHAT BROWSE OFFERS THE COMMAND PALETTE beyond "go to" (DEV_UI 10.1).
 *
 * "Elysium has object types, saved views, actions per type, admin
 * functions and an agent. A sidebar cannot hold that." These build the
 * commands for each, from the schema the host publishes and from data
 * fetched when the palette opens -- never per keystroke, because "the
 * palette opens in under 100ms or it will not be used".
 *
 * BROWSE'S OWN, SUPPLIED TO THE SHELL (step 1.3b): they lived in
 * Elysium's shell, which therefore knew Browse's routes and was handed
 * the schema -- two of the three places the frame broke "a sub-app
 * touches the frame only by declaring". useBrowsePalette (palette.ts)
 * hands them to the shell's palette instead.
 *
 * SCOPED TO WHERE YOU ARE, from GitHub's palette: it "uses [your
 * location] as the scope for suggestions", and "pull request and issue
 * commands always run on the underlying page". So an action is offered
 * on the page of an object it applies to, and nowhere else; listing
 * every action of every type on every screen, each greyed with "open
 * a Customer first", would bury the commands that can run.
 *
 * DISABLED WITH THE REASON inside that scope: an action this reader may
 * see on this type and not run is listed, greyed, with why. That is
 * DEV_UI's rule, and it applies to what the scope offers.
 *
 * EVERY COMMAND IS A LINK. Each one navigates to a URL the destination
 * already understands -- `?type=`, `?saved=`, `?action=`, `?q=` -- so
 * the commands need none of Browse's screens loaded, and anything the
 * palette can reach can also be bookmarked.
 */

import type { Command } from '@shell/core/commands'
import type { VisibleSchema } from '@elysium/shell-api/types'

type Go = (to: string) => void

/** "Browse Customer", one per type the reader may see. */
export function typeCommands(schema: VisibleSchema | null, go: Go): Command[] {
  return Object.keys(schema ?? {})
    .sort((a, b) => a.localeCompare(b))
    .map((type) => ({
      id: `browse:${type}`,
      label: `Browse ${type}`,
      group: 'Object types',
      run: () => go(`/browse?type=${encodeURIComponent(type)}`),
    }))
}

export interface PaletteView {
  view_id: string
  name: string
  object_type: string
}

/** The reader's saved views, by the name they gave them. */
export function viewCommands(views: PaletteView[], go: Go): Command[] {
  return views.map((view) => ({
    id: `view:${view.view_id}`,
    label: view.name,
    group: `Saved views · ${view.object_type}`,
    run: () => go(`/browse?saved=${encodeURIComponent(view.view_id)}`),
  }))
}

/** The object the current page is about, or null. */
export function objectInScope(pathname: string): { type: string; id: string } | null {
  const match = /^\/objects\/([^/]+)\/([^/]+)\/?$/.exec(pathname)
  if (!match) return null
  return { type: decodeURIComponent(match[1]!), id: decodeURIComponent(match[2]!) }
}

export interface PaletteAction {
  affected_object_types: string[]
  executable: boolean
}

/** Actions on the object in scope: runnable ones open its form; ones the
 * reader may see and not run say so. */
export function actionCommands(
  scope: { type: string; id: string } | null,
  actions: Record<string, PaletteAction> | null,
  go: Go,
): Command[] {
  if (scope === null || actions === null) return []
  const here = `/objects/${encodeURIComponent(scope.type)}/${encodeURIComponent(scope.id)}`
  return Object.entries(actions)
    .filter(([, action]) => action.affected_object_types.includes(scope.type))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, action]) => ({
      id: `action:${name}`,
      // THE BUTTON'S OWN LABEL (DEV_UI 10.4: "with the same label as its
      // button") -- the object page's button says the action's name.
      label: name,
      group: `Actions · this ${scope.type}`,
      unavailable: action.executable ? undefined : 'Your role may see this action but not run it',
      run: () => go(`${here}?action=${encodeURIComponent(name)}`),
    }))
}

/** How many types a search is offered in, so a deployment with forty
 * does not push every command below the fold. */
export const MAX_SEARCH_SUGGESTIONS = 5

/**
 * "Search Customer for 'ada'", after whatever matched -- GitHub's
 * "suggested searches based on your search scope". The type being
 * browsed comes first; the rest alphabetically.
 *
 * NOT A SERVER SEARCH. Each one opens Browse with the text in its
 * search box, so the palette still filters only what it holds and
 * stays under 100ms; Browse does the asking.
 */
export function searchSuggestions(
  query: string,
  schema: VisibleSchema | null,
  currentType: string | null,
  go: Go,
): Command[] {
  const text = query.trim()
  if (text === '') return []
  const types = Object.keys(schema ?? {}).sort((a, b) => a.localeCompare(b))
  const ordered =
    currentType && types.includes(currentType) ? [currentType, ...types.filter((t) => t !== currentType)] : types
  return ordered.slice(0, MAX_SEARCH_SUGGESTIONS).map((type) => ({
    id: `search:${type}`,
    label: `Search ${type} for “${text}”`,
    group: 'Search',
    run: () => go(`/browse?type=${encodeURIComponent(type)}&q=${encodeURIComponent(text)}`),
  }))
}
