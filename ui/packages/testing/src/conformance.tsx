/**
 * THE CONFORMANCE SUITE: what every module, Elysium's own included, is
 * held to by default (BLOCKING.md item 3, "COMMON BEHAVIOUR IS TESTED
 * ONCE, BY DEFAULT, UNTIL OVERRIDDEN").
 *
 * A module's own tests call it once:
 *
 *     describeModule({ folder: <its folder>, activate })
 *
 * and get every check below, on every page its module.json declares --
 * Storybook's precedent, where "a basic story is also a smoke test" and
 * every story is tested unless it opts out.
 *
 * OVERRIDES, in `module.conformance.json` beside `module.json`:
 *
 *     { "checks": { "error@schema": { "level": "todo", "reason": "..." } } }
 *
 * keyed by check, or by `check@page` for one page; THE NARROWEST WINS.
 * Levels, after Storybook's accessibility test:
 *   error    (default) a failure fails the suite
 *   todo     runs; a failure is reported, not failed -- and a todo that
 *            now PASSES fails, telling you to raise it, so the list of
 *            todos only shrinks
 *   off      not run
 *   replaced the module's own stronger test covers it; `by` names it as
 *            `<file>::<test name>`, and the suite checks that test exists
 * Anything but `error` needs a `reason`. Data, not code, so one report
 * can list every module's exceptions without running them
 * (python -m scripts.conformance_report).
 *
 * THE CHECKS ARE TESTED THEMSELVES: conformance.test.tsx runs each one
 * on a page built to fail it, and on one built to pass. A check that
 * cannot fail would pass every module for ever.
 */
import { readdirSync, readFileSync } from 'node:fs'
import { join } from 'node:path'
import { checkFeed, CONTRACT_VERSION, type ModuleEntry } from '@shell/core/contract'
import type { ModuleActivation } from '@shell/core/moduleLoader'
import { buildRegistry } from '@shell/core/registry'
import { act, cleanup, waitFor, within } from '@testing-library/react'
import type { ComponentType } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { unlayeredRules } from './css'
import { renderInTestHost, resetTestHost, stubServer } from './host'

/** Checks run once per module. */
export const MODULE_CHECKS = ['manifest', 'layered-css'] as const
/** Checks run on every page the module declares. */
export const PAGE_CHECKS = ['renders', 'loading', 'error', 'session-expired', 'unmount'] as const
export type CheckId = (typeof MODULE_CHECKS)[number] | (typeof PAGE_CHECKS)[number]

export type Level = 'error' | 'todo' | 'off' | 'replaced'
export interface Override {
  level: Exclude<Level, 'error'>
  reason: string
  /** For `replaced`: `<file relative to the module>::<test name>`. */
  by?: string
}

/** A short wait for effects and fetches to settle. */
const settle = () => act(async () => new Promise((resolve) => setTimeout(resolve, 0)))

// ---------------------------------------------------------------------------
// The checks. Each throws when the module fails it.
// ---------------------------------------------------------------------------

/** The page renders inside the shell's frame without throwing. */
async function renders(Page: ComponentType) {
  stubServer({ kind: 'pending' })
  const host = renderInTestHost(<Page />)
  await settle()
  expect(host.container.innerHTML, 'the page rendered nothing at all').not.toBe('')
}

/** While the server has not answered, the page says it is loading. */
async function loading(Page: ComponentType) {
  stubServer({ kind: 'pending' })
  const host = renderInTestHost(<Page />)
  await within(host.container).findByRole('status', {}, { timeout: 2000 })
}

/** When the server fails, the page says so, announced as an alert. */
async function error(Page: ComponentType) {
  stubServer({ kind: 'status', status: 500 })
  const host = renderInTestHost(<Page />)
  await within(host.container).findByRole('alert', {}, { timeout: 2000 })
}

/** When the session has expired, the page hands over to sign-in. */
async function sessionExpired(Page: ComponentType) {
  stubServer({ kind: 'status', status: 401 })
  const host = renderInTestHost(<Page />)
  await waitFor(() => expect(host.hostValues.onSessionExpired).toHaveBeenCalled(), { timeout: 2000 })
}

/**
 * Unmounted, the page leaves nothing running: no interval, no listener
 * on the window or the document. (A state update after unmount is
 * silent since React 18, so it cannot be observed; what keeps running
 * can.)
 */
async function unmount(Page: ComponentType) {
  const intervals = new Set<unknown>()
  const listeners = new Map<string, number>()
  const realSet = window.setInterval.bind(window)
  const realClear = window.clearInterval.bind(window)
  vi.spyOn(window, 'setInterval').mockImplementation(((handler: TimerHandler, ms?: number) => {
    const id = realSet(handler, ms)
    intervals.add(id)
    return id
  }) as typeof window.setInterval)
  vi.spyOn(window, 'clearInterval').mockImplementation(((id?: number) => {
    intervals.delete(id)
    realClear(id)
  }) as typeof window.clearInterval)
  for (const [name, target] of [
    ['window', window],
    ['document', document],
  ] as const) {
    const add = target.addEventListener.bind(target)
    const remove = target.removeEventListener.bind(target)
    vi.spyOn(target, 'addEventListener').mockImplementation((type, listener, options) => {
      listeners.set(`${name}:${type}`, (listeners.get(`${name}:${type}`) ?? 0) + 1)
      add(type, listener, options)
    })
    vi.spyOn(target, 'removeEventListener').mockImplementation((type, listener, options) => {
      listeners.set(`${name}:${type}`, (listeners.get(`${name}:${type}`) ?? 0) - 1)
      remove(type, listener, options)
    })
  }
  const server = stubServer({ kind: 'pending' })
  const host = renderInTestHost(<Page />)
  await settle()
  host.unmount()
  server.settle({ kind: 'status', status: 500 })
  await settle()
  const left = [...listeners].filter(([, count]) => count > 0).map(([key]) => key)
  const running = intervals.size
  // Stopped here so a failing page does not tick on through the rest of the run.
  for (const id of intervals) realClear(id as number)
  expect({ intervals: running, listeners: left }, 'left running after unmount').toEqual({
    intervals: 0,
    listeners: [],
  })
}

/** The manifest is valid against the contract, and `activate` offers
 *  every page it declares. */
async function manifestCheck(manifest: ModuleEntry, activation: ModuleActivation) {
  const home = manifest.contributes.pages?.[0]?.path ?? '/'
  const feed = checkFeed({ contract: CONTRACT_VERSION, home, modules: [{ ...manifest, entry: null }] })
  expect(buildRegistry(feed).problems, 'the registry could not honour the manifest').toEqual([])
  const declared = (manifest.contributes.pages ?? []).map((page) => page.id)
  const missing = declared.filter((id) => !(id in activation.pages))
  expect(missing, '`activate` does not offer these declared pages').toEqual([])
}

/** Every rule the module's own stylesheets author sits inside a layer. */
async function layeredCss(folder: string) {
  const offenders: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) walk(path)
      else if (entry.name.endsWith('.css')) {
        for (const rule of unlayeredRules(readFileSync(path, 'utf8'))) offenders.push(`${entry.name}: ${rule}`)
      }
    }
  }
  walk(join(folder, 'src'))
  expect(offenders, 'rules outside every @layer beat every layer').toEqual([])
}

/** The checks by id, for the suite and for its own tests. */
export const PAGE_CHECK_FUNCTIONS: Record<(typeof PAGE_CHECKS)[number], (Page: ComponentType) => Promise<void>> = {
  renders,
  loading,
  error,
  'session-expired': sessionExpired,
  unmount,
}
export { manifestCheck, layeredCss }

// ---------------------------------------------------------------------------
// Overrides
// ---------------------------------------------------------------------------

const ALL_CHECKS: readonly string[] = [...MODULE_CHECKS, ...PAGE_CHECKS]

/** A module's overrides, refused rather than half-read if malformed. */
export function readOverrides(folder: string, pageIds: readonly string[]): Record<string, Override> {
  let raw: unknown
  try {
    raw = JSON.parse(readFileSync(join(folder, 'module.conformance.json'), 'utf8'))
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === 'ENOENT') return {}
    throw new Error(`${folder}/module.conformance.json: ${String(e)}`)
  }
  const checks = (raw as { checks?: Record<string, Override> }).checks ?? {}
  for (const [key, override] of Object.entries(checks)) {
    const [check, page] = key.split('@')
    if (!ALL_CHECKS.includes(check ?? '')) throw new Error(`module.conformance.json: no check called ${check}`)
    if (page !== undefined && !pageIds.includes(page)) {
      throw new Error(`module.conformance.json: ${key} names a page the manifest does not declare`)
    }
    if (!['todo', 'off', 'replaced'].includes(override.level)) {
      throw new Error(`module.conformance.json: ${key} has level ${override.level}; use todo, off or replaced`)
    }
    if (!override.reason?.trim()) throw new Error(`module.conformance.json: ${key} needs a reason`)
    if (override.level === 'replaced' && !override.by?.includes('::')) {
      throw new Error(`module.conformance.json: ${key} is replaced, and needs \`by\`: "<file>::<test name>"`)
    }
  }
  return checks
}

/** The level for a check, the narrowest setting winning. */
export function levelFor(overrides: Record<string, Override>, check: CheckId, pageId?: string): Setting {
  return (pageId !== undefined ? overrides[`${check}@${pageId}`] : undefined) ?? overrides[check] ?? { level: 'error' }
}

// ---------------------------------------------------------------------------
// The suite
// ---------------------------------------------------------------------------

type Setting = Override | { level: 'error' }

/**
 * What a check does at its level: the test body, or null when it is off.
 * Apart from `describeModule` so the levels are tested themselves --
 * above all the ratchet, a todo that passes failing, which a suite can
 * only observe from outside the test it fails.
 */
export function atLevel(
  setting: Setting,
  run: () => Promise<void>,
  where: { module: string; check: string; folder: string },
): (() => Promise<void>) | null {
  switch (setting.level) {
    case 'error':
      return run
    case 'off':
      return null
    case 'replaced':
      return async () => {
        const [file = '', testName = ''] = (setting.by ?? '').split('::')
        let source = ''
        try {
          source = readFileSync(join(where.folder, file), 'utf8')
        } catch {
          throw new Error(`${where.check} is replaced by ${setting.by}, and ${file} does not exist`)
        }
        if (!source.includes(testName)) {
          throw new Error(`${where.check} is replaced by ${setting.by}, and ${file} has no such test`)
        }
      }
    case 'todo':
      return async () => {
        try {
          await run()
        } catch (failure) {
          console.warn(
            `[conformance] ${where.module}: ${where.check} still fails (todo: ${setting.reason})\n${String(failure)}`,
          )
          return
        }
        throw new Error(`${where.check} now passes: remove its todo from module.conformance.json, so it is held to it`)
      }
  }
}

export interface ModuleUnderTest {
  /** The module's folder, holding module.json. */
  folder: string
  /** Its entry's `activate`. */
  activate: () => ModuleActivation | Promise<ModuleActivation>
}

export function describeModule(module: ModuleUnderTest): void {
  const manifest = JSON.parse(readFileSync(join(module.folder, 'module.json'), 'utf8')) as ModuleEntry
  const pageIds = (manifest.contributes.pages ?? []).map((page) => page.id)
  const overrides = readOverrides(module.folder, pageIds)

  const define = (name: string, setting: Setting, run: () => Promise<void>) => {
    const body = atLevel(setting, run, { module: manifest.id, check: name, folder: module.folder })
    if (body === null) return it.skip(`${name} -- off: ${(setting as Override).reason}`, () => {})
    const { level, reason, by } = setting as { level: Level; reason?: string; by?: string }
    const label = level === 'error' ? name : `${name} -- ${level}${by ? ` by ${by}` : ''}: ${reason}`
    return it(label, body)
  }

  describe(`module ${manifest.id}: conformance`, () => {
    afterEach(() => {
      cleanup()
      vi.restoreAllMocks()
      vi.unstubAllGlobals()
      resetTestHost()
    })

    define('manifest: valid, and activate offers every declared page', levelFor(overrides, 'manifest'), async () =>
      manifestCheck(manifest, await module.activate()),
    )
    define('layered-css: every rule inside a layer', levelFor(overrides, 'layered-css'), async () =>
      layeredCss(module.folder),
    )
    for (const pageId of pageIds) {
      for (const check of PAGE_CHECKS) {
        define(`${check} @ ${pageId}`, levelFor(overrides, check, pageId), async () => {
          const Page = (await module.activate()).pages[pageId]
          if (Page === undefined) throw new Error(`activate offers no page called ${pageId}`)
          await PAGE_CHECK_FUNCTIONS[check](Page)
        })
      }
    }
  })
}
