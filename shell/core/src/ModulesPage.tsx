/**
 * THE MODULES PAGE: the shell's system sub-app (BLOCKING.md item 3,
 * step 1.4) -- every module this person is offered, and how each stands
 * in this browser.
 *
 * GENERIC: it reads the feed (the contract) and the loader, nothing of
 * any backend. A host mounts it as the page of its system module, which
 * the backend marks `pinned` so it loads in safe mode and nothing in the
 * interface turns it off.
 *
 * LIVE: the "in this browser" column follows the loader as modules load,
 * fail and unload (`ModuleLoader.subscribe`), so opening another tab of
 * the app is not needed to see a module arrive.
 */
import { HTMLTable, Tag } from '@blueprintjs/core'
import { useSyncExternalStore } from 'react'
import { activatesOn, apiRefusal, type ModuleEntry, type ModuleFeed } from './contract'
import type { ModuleLoader, ModuleStatus } from './moduleLoader'
import { ModuleArrangementEditor, type ModuleManager } from './ModuleArrangementEditor'

export interface ModulesPageProps {
  /** Every module offered -- in safe mode too, so the page can say
   *  which ones safe mode left out. */
  feed: ModuleFeed
  loader: Pick<ModuleLoader, 'status' | 'subscribe' | 'snapshot'>
  /** The page is in safe mode: modules not pinned are not loaded. */
  safeMode?: boolean
  /** Given to someone who may change the deployment's modules: the page
   *  then offers the arrangement for everyone (ModuleArrangementEditor). */
  manager?: ModuleManager
}

/** How a status reads to a person. */
export function describeStatus(module: ModuleEntry, status: ModuleStatus): string {
  switch (status.state) {
    case 'built-in':
      return 'Part of the page'
    case 'loading':
      return 'Loading…'
    case 'loaded':
      return 'Loaded'
    case 'failed':
      return `Could not be loaded: ${status.reason}`
    case 'not-loaded':
      return activatesOn(module, 'onStartup')
        ? 'Not loaded yet — loads with the page'
        : activatesOn(module, 'onPalette')
          ? 'Not loaded yet — loads when a page of it, or the palette, opens'
          : 'Not loaded yet — loads when one of its pages opens'
  }
}

export function ModulesPage({ feed, loader, safeMode = false, manager }: ModulesPageProps) {
  useSyncExternalStore(loader.subscribe, loader.snapshot)
  return (
    <section className="modules-page">
      <h2>Modules</h2>
      <p>
        The sub-apps this deployment offers you, in the order of the rail, and how each stands in this browser.
        Pinned ones are the system&apos;s own: they load in safe mode and cannot be turned off here.
      </p>
      <HTMLTable compact striped className="modules-page__table">
        <thead>
          <tr>
            <th scope="col">Module</th>
            <th scope="col">Version</th>
            <th scope="col">Its code</th>
            <th scope="col">In this browser</th>
            <th scope="col">On the rail</th>
          </tr>
        </thead>
        <tbody>
          {feed.modules.map((module) => {
            const status = loader.status(module)
            // NOT LOADABLE HERE AT ALL (step 4): the page leaves it out of
            // the rail and the routes, and this is where it says why.
            const refusal = apiRefusal(module)
            return (
              <tr key={module.id}>
                <th scope="row">
                  {module.name} <span className="modules-page__id">{module.id}</span>
                  {module.pinned && (
                    <Tag minimal className="modules-page__pinned">
                      Pinned
                    </Tag>
                  )}
                </th>
                <td>{module.version}</td>
                <td>{module.entry === null ? 'Built into the page' : 'Its own bundle'}</td>
                <td className={status.state === 'failed' || refusal !== null ? 'modules-page__failed' : undefined}>
                  {refusal !== null
                    ? `Not loaded: ${refusal}`
                    : safeMode && !module.pinned
                      ? 'Off in safe mode'
                      : describeStatus(module, status)}
                </td>
                <td>{(module.contributes.nav ?? []).map((entry) => entry.title).join(', ') || '—'}</td>
              </tr>
            )
          })}
        </tbody>
      </HTMLTable>
      {manager && <ModuleArrangementEditor manager={manager} />}
    </section>
  )
}
