/**
 * SLOTS (BLOCKING.md item 3, step 1.5): a place a module's page offers to
 * other modules -- Backstage's extension "input", where a child names
 * "the ID of the parent extension, as well as the name of the input to
 * attach to", and the parent receives "an array, where each individual
 * item is an extension that attached itself"; Grafana's "extension point".
 *
 * DECLARED IN MANIFESTS, both sides (contract.ts): the owner's `slots`,
 * with the order it wants, and each contributor's `into` -- so the shell
 * knows every contribution, its title and icon, without loading any code.
 * The component comes from the contributor's code when the slot first
 * shows it, through the same `activate` as palette commands and badges.
 *
 * THE OWNER DRAWS IT. `useSlot(id)` gives the contributions -- from the
 * modules the feed offers this person, so safe mode and permissions apply
 * without the owner doing anything -- each with a ready component the
 * owner renders with whatever context the slot promises (props), inside
 * its own Suspense.
 *
 * ONE MODULE CANNOT BREAK ANOTHER'S SCREEN: each contribution renders
 * inside an error boundary of its own, and a contribution whose code
 * fails to load or throws shows "could not be loaded" -- with the
 * safe-mode link -- in its own place, leaving the owner's page and every
 * other contribution standing.
 */
import { Component, createContext, lazy, useContext, type ComponentType, type ErrorInfo, type ReactNode } from 'react'
import type { FrameModules, ModuleActivator } from './activation'
import type { ModuleEntry, SlotContribution } from './contract'
import { ModuleLoadFailed } from './moduleLoader'

/** One contribution in a slot, ready to draw. */
export interface SlotItem<P extends object> {
  moduleId: string
  id: string
  title: string
  icon?: string
  Component: ComponentType<P>
}

const SlotsContext = createContext<FrameModules | undefined>(undefined)

/** Makes the feed's modules available to `useSlot` below. The frame
 *  puts it around every page. */
export function SlotsProvider({ modules, children }: { modules: FrameModules | undefined; children: ReactNode }) {
  return <SlotsContext.Provider value={modules}>{children}</SlotsContext.Provider>
}

/** Contains a contribution's failure to its own place. */
class ContributionBoundary extends Component<{ moduleId: string; children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Said in the console for whoever investigates; the page says it too.
    console.error(`[slots] ${this.props.moduleId} failed`, error, info.componentStack)
  }

  render() {
    return this.state.error ? (
      <ModuleLoadFailed moduleId={this.props.moduleId} reason={this.state.error.message} />
    ) : (
      this.props.children
    )
  }
}

/**
 * One stable component per contribution, per activator: React must see
 * the same component type on every render, or it would remount the
 * contribution -- losing its state -- whenever the owner re-rendered.
 */
const components = new WeakMap<ModuleActivator, Map<string, ComponentType<object>>>()

function componentFor(activate: ModuleActivator, module: ModuleEntry, contribution: SlotContribution) {
  let cache = components.get(activate)
  if (cache === undefined) {
    cache = new Map()
    components.set(activate, cache)
  }
  const key = `${module.id}@${module.entry ?? ''}:${contribution.id}`
  let made = cache.get(key)
  if (made === undefined) {
    const Loaded = lazy(async () => {
      const code = await activate(module)
      const Contributed = code?.contributions?.[contribution.id] as ComponentType<object> | undefined
      if (Contributed === undefined) {
        throw new Error(`its code offers no contribution called ${contribution.id}`)
      }
      return { default: Contributed }
    })
    const InBoundary = (props: object) => (
      <ContributionBoundary moduleId={module.id}>
        <Loaded {...props} />
      </ContributionBoundary>
    )
    InBoundary.displayName = `Contribution(${module.id}:${contribution.id})`
    made = InBoundary
    cache.set(key, made)
  }
  return made
}

/**
 * The contributions to slot `slotId`, in the order its owner declares --
 * the ids it lists first, in that order, then the rest in feed order --
 * from the modules the feed offers. Empty outside a SlotsProvider.
 */
export function useSlot<P extends object>(slotId: string): SlotItem<P>[] {
  const modules = useContext(SlotsContext)
  if (modules === undefined) return []
  const declared = modules.feed
    .flatMap((module) => module.contributes.slots ?? [])
    .find((slot) => slot.id === slotId)
  const order = declared?.order ?? []
  const items = modules.feed.flatMap((module) =>
    (module.contributes.into ?? [])
      .filter((contribution) => contribution.slot === slotId)
      .map((contribution) => ({
        moduleId: module.id,
        id: contribution.id,
        title: contribution.title,
        icon: contribution.icon,
        Component: componentFor(modules.activate, module, contribution) as ComponentType<P>,
      })),
  )
  const rank = (id: string) => {
    const at = order.indexOf(id)
    return at === -1 ? order.length : at
  }
  // A STABLE SORT keeps feed order among the ids the owner did not list.
  return items.sort((a, b) => rank(a.id) - rank(b.id))
}
