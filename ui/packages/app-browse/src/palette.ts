/**
 * BROWSE'S PALETTE HOOK (BLOCKING.md item 3, step 1.3b): what Browse
 * hands the shell's command palette. Browse's manifest names the
 * `onPalette` activation event, so the shell runs this once the palette
 * first opens, whether or not Browse's screens have been visited.
 *
 * Moved from Elysium's Shell.tsx with the reasoning that shaped it:
 *
 * WHAT IT FETCHES, AND WHEN: the reader's saved views and the action
 * types, each time the palette OPENS -- not per keystroke, and not on
 * every page load for a palette most loads never open. The list it
 * filters is in memory by the time anyone types (DEV_UI 10.1: "opens in
 * under 100ms or it will not be used"); a view saved a minute ago is
 * there next time it opens.
 *
 * A FAILURE IS FEWER COMMANDS, not an error in the palette: navigation
 * and types still work, and a session that has expired is noticed by
 * whatever the page itself asks next.
 *
 * THE ORDER IS THE ONE A PERSON REACHES IN: actions on the object in
 * front of them before the shell's navigation, then types, then their
 * own views.
 */
import { getSavedViews, getVisibleActionTypesCached } from '@elysium/shell-api/api'
import { useHostValues } from '@elysium/shell-api/host'
import type { PaletteContribution } from '@shell/core/palette'
import { useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import {
  actionCommands,
  objectInScope,
  type PaletteAction,
  type PaletteView,
  searchSuggestions,
  typeCommands,
  viewCommands,
} from './paletteCommands'

export function useBrowsePalette({ open }: { open: boolean }): PaletteContribution {
  const { visibleSchema } = useHostValues()
  const location = useLocation()
  const navigate = useNavigate()
  const [views, setViews] = useState<PaletteView[]>([])
  const [actions, setActions] = useState<Record<string, PaletteAction> | null>(null)

  useEffect(() => {
    if (!open) return
    let current = true
    getSavedViews().then(
      (found) => current && setViews(found),
      () => current && setViews([]),
    )
    getVisibleActionTypesCached().then(
      (found) => current && setActions(found as Record<string, PaletteAction>),
      () => current && setActions(null),
    )
    return () => {
      current = false
    }
  }, [open])

  const go = (to: string) => void navigate(to)
  const scope = objectInScope(location.pathname)
  const browsingType = location.pathname.startsWith('/browse')
    ? new URLSearchParams(location.search).get('type')
    : (scope?.type ?? null)
  return {
    before: actionCommands(scope, actions, go),
    after: [...typeCommands(visibleSchema, go), ...viewCommands(views, go)],
    suggest: (query) => searchSuggestions(query, visibleSchema, browsingType, go),
  }
}
