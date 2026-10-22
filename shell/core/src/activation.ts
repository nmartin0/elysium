/**
 * ACTIVATING MODULES ON EVENTS (BLOCKING.md item 3, step 1.3).
 *
 * A module's code runs when one of its pages opens, or on an event its
 * manifest names -- VS Code's activation events, where an extension is
 * "activated lazily" on the events it lists:
 *
 *   onPalette   the first time the command palette opens: its commands
 *               are listed before any of its pages has been visited
 *   onStartup   as soon as the frame is drawn: a badge on its rail entry
 *               is on every screen from the start
 *
 * THE HOST SAYS HOW, THE SHELL SAYS WHEN. The host's `activate(module)`
 * returns the module's code -- from its bundle (the loader's `load`), or
 * the host's own for a module built into the page -- and the shell calls
 * it on the module's events and reads what it needs: `usePalette` for
 * the palette, `useBadges` for the rail. A module that does not name an
 * event is not activated for it, whatever its code holds: the manifest
 * is what the shell trusts to decide what loads.
 *
 * A MODULE THAT FAILS TO ACTIVATE gives nothing, quietly -- neither the
 * palette nor the rail is where its failure belongs, and its own page
 * says so when opened -- and is asked again the next time its event
 * comes round.
 */
import { useEffect, useRef, useState, type ComponentType } from 'react'
import { activatesOn, type ActivationEvent, type ModuleEntry } from './contract'
import type { PaletteHook } from './palette'
import type { BadgeHook } from './badges'

/** What the shell reads of a module's code, beyond its pages. */
export interface ModuleCode {
  /** Its palette commands; read for a module naming `onPalette`. */
  usePalette?: PaletteHook
  /** The badges on its own rail entries; read for one naming `onStartup`. */
  useBadges?: BadgeHook
  /** Its contributions to other modules' slots, by the ids its manifest's
   *  `into` declares (slots.tsx). */
  contributions?: Record<string, ComponentType<never>>
}

/** The host's way to a module's code. `undefined`: it has none to give. */
export type ModuleActivator = (module: ModuleEntry) => ModuleCode | undefined | Promise<ModuleCode | undefined>

/** The feed's modules, and how the host activates one. */
export interface FrameModules {
  feed: readonly ModuleEntry[]
  activate: ModuleActivator
}

/**
 * The code of the modules naming `event`, activated once `when` is true;
 * in feed order, and only modules the feed still offers.
 */
export function useActivated(
  modules: FrameModules | undefined,
  event: ActivationEvent,
  when: boolean,
): { module: ModuleEntry; code: ModuleCode }[] {
  const [activated, setActivated] = useState<ReadonlyMap<string, ModuleCode>>(new Map())
  const asked = useRef(new Set<string>())
  const mounted = useRef(true)
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
    }
  }, [])

  useEffect(() => {
    if (!when || modules === undefined) return
    for (const module of modules.feed) {
      if (!activatesOn(module, event) || asked.current.has(module.id)) continue
      asked.current.add(module.id)
      // NOT CANCELLED BY `when` TURNING FALSE: a module still loading
      // when the palette closes is there the next time it opens.
      void Promise.resolve()
        .then(() => modules.activate(module))
        .then(
          (code) => {
            if (mounted.current && code !== undefined) {
              setActivated((previous) => new Map(previous).set(module.id, code))
            }
          },
          () => {
            asked.current.delete(module.id)
          },
        )
    }
  }, [when, modules, event])

  return (modules?.feed ?? []).flatMap((module) => {
    const code = activated.get(module.id)
    return code !== undefined && activatesOn(module, event) ? [{ module, code }] : []
  })
}
