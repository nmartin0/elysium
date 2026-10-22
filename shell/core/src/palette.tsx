/**
 * PALETTE COMMANDS SUPPLIED BY MODULES (BLOCKING.md item 3, step 1.3b).
 *
 * The frame's palette lists its own navigation commands and whatever the
 * modules' code supplies. A module's `activate` may return `usePalette`,
 * a React HOOK: it is given whether the palette is open and returns the
 * module's commands -- some to list `before` the navigation commands
 * (what acts on the page in front of you), some `after` -- and the
 * suggestions it makes from typed text.
 *
 * A HOOK, because what a module lists depends on things that change:
 * where the person is, data loaded when the palette opens, values the
 * host publishes. Each hook runs inside a component of its own that the
 * frame mounts, so the rules of hooks hold however many modules supply
 * one, and a module's state changing re-renders only that component.
 *
 * WHEN THE CODE LOADS: a module whose manifest names the `onPalette`
 * activation event is activated the first time the palette opens, so
 * its commands are there before any of its pages has been visited --
 * VS Code's activation events, where an extension is "activated lazily"
 * on the events it names. A module that does not name it contributes
 * nothing to the palette, whatever its code returns: the manifest is
 * what the shell trusts to decide what loads.
 *
 * A MODULE THAT FAILS TO LOAD contributes nothing, quietly: the palette
 * is not where its failure belongs, and its own page says so when opened.
 */
import { memo, useCallback, useEffect, useRef, useState } from 'react'
import type { Command } from './commands'
import { activatesOn, type ModuleEntry } from './contract'

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

/** The hook a module supplies, once its code is loaded: from the bundle's
 *  activation, or from the host for a module built into the page.
 *  `undefined` when it supplies none. */
export type PaletteResolver = (
  module: ModuleEntry,
) => PaletteHook | undefined | Promise<PaletteHook | undefined>

export interface ModulePalettes {
  modules: readonly ModuleEntry[]
  resolve: PaletteResolver
}

/**
 * The palette hooks of the modules that activate on the palette, loaded
 * the first time it opens; in feed order. A module the feed stops
 * offering drops out.
 */
export function useModulePalettes(
  palettes: ModulePalettes | undefined,
  open: boolean,
): { id: string; usePalette: PaletteHook }[] {
  const [loaded, setLoaded] = useState<ReadonlyMap<string, PaletteHook>>(new Map())
  const asked = useRef(new Set<string>())
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!open || palettes === undefined) return
    for (const module of palettes.modules) {
      if (!activatesOn(module, 'onPalette') || asked.current.has(module.id)) continue
      asked.current.add(module.id)
      // NOT CANCELLED BY CLOSING THE PALETTE: a module still loading when
      // it closes is there the next time it opens.
      void Promise.resolve()
        .then(() => palettes.resolve(module))
        .then(
          (hook) => {
            if (mounted.current && hook !== undefined) setLoaded((previous) => new Map(previous).set(module.id, hook))
          },
          () => {
            // Nothing for the palette (see the header); asked again the
            // next time it opens.
            asked.current.delete(module.id)
          },
        )
    }
  }, [open, palettes])

  const offered = palettes?.modules ?? []
  return offered.flatMap((module) => {
    const usePalette = loaded.get(module.id)
    return usePalette !== undefined && activatesOn(module, 'onPalette') ? [{ id: module.id, usePalette }] : []
  })
}

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
