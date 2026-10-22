/**
 * BADGES ON RAIL ENTRIES (BLOCKING.md item 3, step 1.3c).
 *
 * A number on a module's rail entry -- how much is waiting -- drawn by
 * the frame in its own style. The module's code supplies the number
 * through `useBadges`, a React hook returning badges keyed by the paths
 * of ITS OWN rail entries; a badge for any other path is ignored, so no
 * module can mark another's tab. VS Code's precedent: an extension sets
 * a view's `badge` -- a `value` and a `tooltip` -- and the workbench
 * draws it.
 *
 * WHEN ITS CODE RUNS: a badge is on every screen, so the module names
 * the `onStartup` activation event and is activated as soon as the frame
 * is drawn (activation.ts). Owner's decision, 21 October: THE RAIL IS
 * THE ONLY PLACE -- it is present at every width, so a badge there is on
 * every screen, and the header has no module slots at all.
 *
 * NOTHING WAITING, NO BADGE: a count of zero, or none, draws nothing.
 */
import { memo, useCallback, useEffect, useState } from 'react'

export interface Badge {
  /** How many; above 99 it is drawn as "99+". */
  count: number
  /** What the count is, for someone who cannot see it: "3 waiting".
   *  Read after the entry's own name. */
  label: string
}

/** A module's badge hook: badges by the path of its own rail entries. */
export type BadgeHook = () => Readonly<Record<string, Badge | undefined>>

/** Runs one module's badge hook and reports what it returns. Renders
 *  nothing; memoised, so the frame re-rendering on a report does not
 *  re-run every module's hook. */
export const BadgeSource = memo(function BadgeSource({
  id,
  useBadges,
  report,
}: {
  id: string
  useBadges: BadgeHook
  report: (id: string, badges: Readonly<Record<string, Badge | undefined>>) => void
}) {
  const badges = useBadges()
  useEffect(() => {
    report(id, badges)
  })
  return null
})

/** What the sources report, by module, and a stable reporter. */
export function useBadgeReports(): [
  ReadonlyMap<string, Readonly<Record<string, Badge | undefined>>>,
  (id: string, badges: Readonly<Record<string, Badge | undefined>>) => void,
] {
  const [reports, setReports] = useState<ReadonlyMap<string, Readonly<Record<string, Badge | undefined>>>>(new Map())
  const report = useCallback((id: string, badges: Readonly<Record<string, Badge | undefined>>) => {
    setReports((previous) => new Map(previous).set(id, badges))
  }, [])
  return [reports, report]
}

/** How a count is drawn: whole numbers, capped so the badge stays small. */
export function badgeText(count: number): string {
  return count > 99 ? '99+' : String(count)
}
