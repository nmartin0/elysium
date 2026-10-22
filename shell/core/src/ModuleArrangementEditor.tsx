/**
 * THE MODULE MANAGER'S EDITOR (BLOCKING.md item 3, step 1.4c): turn
 * modules on and off, order the rail, choose where people land -- FOR
 * EVERYONE on the deployment, saved by the backend (Elysium writes
 * modules.yaml through its validated, audited configuration path).
 *
 * GENERIC: it speaks the contract's shapes (ModuleArrangement) through
 * functions the host gives it, so the host's own client -- its session,
 * its CSRF header, its error messages -- does the talking.
 *
 * A DRAFT, SAVED AS ONE: nothing changes until Save, and Discard puts the
 * draft back. A save made against an arrangement someone else has since
 * changed is refused by the backend rather than merged; the message says
 * to reload.
 *
 * PINNED MODULES ARE SHOWN, NOT ARRANGED: always on, always last.
 */
import { Button, HTMLSelect, Switch } from '@blueprintjs/core'
import { useEffect, useState } from 'react'
import type { ArrangedModule, ModuleArrangement, ModuleArrangementChange } from './contract'

export interface ModuleManager {
  read: () => Promise<ModuleArrangement>
  save: (change: ModuleArrangementChange) => Promise<ModuleArrangement>
  /** Fetches the feed again, so the rail follows a save at once and a
   *  rebuilt bundle is loaded from its new address. */
  refresh: () => Promise<void>
}

interface Draft {
  home: string
  /** The arrangeable modules, in rail order, each on or off. */
  order: ArrangedModule[]
}

function draftOf(arrangement: ModuleArrangement): Draft {
  return { home: arrangement.home, order: arrangement.modules.filter((m) => !m.pinned) }
}

const message = (error: unknown) => (error instanceof Error ? error.message : String(error))

/** Pages a person can land on: a module's own pages with no parameter in
 *  the path -- `/objects/:type/:id` is a place one is sent, not a home. */
function homes(modules: ArrangedModule[]): string[] {
  return modules.filter((m) => m.enabled).flatMap((m) => m.pages.filter((path) => !path.includes(':')))
}

export function ModuleArrangementEditor({ manager }: { manager: ModuleManager }) {
  const [saved, setSaved] = useState<ModuleArrangement | null>(null)
  const [draft, setDraft] = useState<Draft | null>(null)
  const [failure, setFailure] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    let current = true
    manager.read().then(
      (arrangement) => {
        if (!current) return
        setSaved(arrangement)
        setDraft(draftOf(arrangement))
      },
      (error: unknown) => current && setFailure(`The arrangement could not be read: ${message(error)}`),
    )
    return () => {
      current = false
    }
  }, [manager])

  if (draft === null || saved === null) {
    return failure === null ? null : (
      <p role="alert" className="modules-page__failed">
        {failure}
      </p>
    )
  }

  const pinned = saved.modules.filter((m) => m.pinned)
  const changed = JSON.stringify(draftOf(saved)) !== JSON.stringify(draft)
  const homeChoices = homes([...draft.order, ...pinned])

  const edit = (next: Draft) => {
    setNotice(null)
    setFailure(null)
    setDraft(next)
  }
  const toggle = (id: string, enabled: boolean) =>
    edit({ ...draft, order: draft.order.map((m) => (m.id === id ? { ...m, enabled } : m)) })
  const move = (index: number, by: -1 | 1) => {
    const order = [...draft.order]
    const [taken] = order.splice(index, 1)
    order.splice(index + by, 0, taken!)
    edit({ ...draft, order })
  }

  async function save() {
    if (draft === null || saved === null) return
    setBusy(true)
    setFailure(null)
    try {
      const next = await manager.save({
        home: draft.home,
        modules: draft.order.map((m) => [m.id, m.enabled]),
        digest: saved.digest,
      })
      setSaved(next)
      setDraft(draftOf(next))
      setNotice('Saved. Every open page picks it up on its next request; this one already has.')
      await manager.refresh()
    } catch (error) {
      setFailure(`Not saved: ${message(error)}`)
    } finally {
      setBusy(false)
    }
  }

  async function refresh() {
    setBusy(true)
    setFailure(null)
    try {
      await manager.refresh()
      setNotice('Refreshed. A module rebuilt since this page loaded is loaded anew when one of its pages opens.')
    } catch (error) {
      setFailure(`Not refreshed: ${message(error)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="modules-page__arrangement" aria-labelledby="modules-arrangement">
      <h3 id="modules-arrangement">Arrangement, for everyone</h3>
      <p>
        Which modules this deployment loads, in the order of the rail, and where people land after signing in.
        Nothing changes until you save.
      </p>
      <ol className="modules-page__order">
        {draft.order.map((module, index) => (
          <li key={module.id}>
            <Switch
              checked={module.enabled}
              label={module.name}
              onChange={(event) => toggle(module.id, event.currentTarget.checked)}
            />
            <span className="modules-page__moves">
              <Button
                minimal
                small
                icon="arrow-up"
                aria-label={`Move ${module.name} up`}
                disabled={index === 0}
                onClick={() => move(index, -1)}
              />
              <Button
                minimal
                small
                icon="arrow-down"
                aria-label={`Move ${module.name} down`}
                disabled={index === draft.order.length - 1}
                onClick={() => move(index, 1)}
              />
            </span>
          </li>
        ))}
        {pinned.map((module) => (
          <li key={module.id} className="modules-page__pinned-row">
            <Switch checked disabled label={module.name} />
            <span>Pinned: always on, always last</span>
          </li>
        ))}
      </ol>
      <label className="modules-page__home">
        Where people land after signing in{' '}
        <HTMLSelect value={draft.home} onChange={(event) => edit({ ...draft, home: event.currentTarget.value })}>
          {(homeChoices.includes(draft.home) ? homeChoices : [draft.home, ...homeChoices]).map((path) => (
            <option key={path} value={path}>
              {path}
            </option>
          ))}
        </HTMLSelect>
      </label>
      <div className="modules-page__actions">
        <Button intent="primary" text="Save" disabled={!changed || busy} onClick={() => void save()} />
        <Button text="Discard" disabled={!changed || busy} onClick={() => edit(draftOf(saved))} />
        <Button minimal icon="refresh" text="Refresh modules" disabled={busy} onClick={() => void refresh()} />
      </div>
      {failure !== null && (
        <p role="alert" className="modules-page__failed">
          {failure}
        </p>
      )}
      {notice !== null && <p role="status">{notice}</p>}
    </section>
  )
}
