/**
 * PALETTE COMMANDS SUPPLIED BY MODULES (BLOCKING.md item 3, step 1.3b).
 *
 * The frame's palette lists its own navigation commands and whatever the
 * modules' code supplies. A module's code may hold `usePalette`, a React
 * HOOK: it is given whether the palette is open and returns the module's
 * commands -- some to list `before` the navigation commands (what acts on
 * the page in front of you), some `after` -- and the suggestions it makes
 * from typed text.
 *
 * A HOOK, because what a module lists depends on things that change:
 * where the person is, data loaded when the palette opens, values the
 * host publishes. Each hook runs inside a component of its own that the
 * frame mounts, so the rules of hooks hold however many modules supply
 * one, and a module's state changing re-renders only that component.
 *
 * WHEN ITS CODE LOADS: on the `onPalette` activation event, the first
 * time the palette opens (activation.ts).
 */
import { memo, useCallback, useEffect, useState } from 'react'
import type { Command } from './commands'

/** What one module offers the palette. */
export interface PaletteContribution {
  /** Listed before the navigation commands. */
  before?: Command[]
  /** Listed after them. */
  after?: Command[]
  /** Commands made from typed text, listed after every match. */
  suggest?: (query: string) => Command[]
}

/** A module's palette hook. */
export type PaletteHook = (palette: { open: boolean }) => PaletteContribution

/** Runs one module's palette hook and reports what it returns. Renders
 *  nothing. Memoised, so the frame re-rendering on a report does not
 *  re-run every module's hook -- each re-runs on its own changes. */
export const PaletteSource = memo(function PaletteSource({
  id,
  usePalette,
  open,
  report,
}: {
  id: string
  usePalette: PaletteHook
  open: boolean
  report: (id: string, contribution: PaletteContribution) => void
}) {
  const contribution = usePalette({ open })
  useEffect(() => {
    report(id, contribution)
  })
  return null
})

/**
 * The frame's state for what the sources report, and a stable reporter.
 * A module that leaves the feed keeps its last report here, unread: the
 * frame reads only the sources it still mounts.
 */
export function useContributions(): [
  ReadonlyMap<string, PaletteContribution>,
  (id: string, contribution: PaletteContribution) => void,
] {
  const [contributions, setContributions] = useState<ReadonlyMap<string, PaletteContribution>>(new Map())
  const report = useCallback((id: string, contribution: PaletteContribution) => {
    setContributions((previous) => new Map(previous).set(id, contribution))
  }, [])
  return [contributions, report]
}
