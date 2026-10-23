/**
 * THE CONFORMANCE SUITE, TESTED: every check fails the page built to
 * fail it and passes the page built to pass (samples.tsx). A check that
 * could not fail would pass every module for ever -- BLOCKING.md item 3:
 * "the suite is tested itself, with a broken sample".
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import type { ModuleEntry } from '@shell/core/contract'
import { cleanup } from '@testing-library/react'
import type { ComponentType } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { getCurrentUser } from '@elysium/shell-api/api'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import {
  asSlotted,
  atLevel,
  layeredCss,
  levelFor,
  manifestCheck,
  PAGE_CHECK_FUNCTIONS,
  readOverrides,
} from './conformance'
import { resetTestHost } from './host'
import {
  BlankPage,
  GoodPage,
  IgnoresSessionExpiryPage,
  LeavesAListenerPage,
  LeavesAnIntervalPage,
  SilentWhileLoadingPage,
  UnannouncedErrorPage,
} from './samples'

afterEach(() => {
  cleanup()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  resetTestHost()
})

/** Runs one check as the suite would, reporting whether it passed. */
async function outcome(check: keyof typeof PAGE_CHECK_FUNCTIONS, Page: ComponentType): Promise<'pass' | 'fail'> {
  try {
    await PAGE_CHECK_FUNCTIONS[check](Page)
    return 'pass'
  } catch {
    return 'fail'
  } finally {
    cleanup()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  }
}

describe('each page check fails the page built to fail it, and passes a good one', () => {
  const broken: [keyof typeof PAGE_CHECK_FUNCTIONS, ComponentType][] = [
    ['renders', BlankPage],
    ['loading', SilentWhileLoadingPage],
    ['error', UnannouncedErrorPage],
    ['session-expired', IgnoresSessionExpiryPage],
    ['unmount', LeavesAnIntervalPage],
    ['unmount', LeavesAListenerPage],
  ]
  it.each(broken)('%s fails %o', async (check, Page) => {
    expect(await outcome(check, Page)).toBe('fail')
  })
  it.each(Object.keys(PAGE_CHECK_FUNCTIONS) as (keyof typeof PAGE_CHECK_FUNCTIONS)[])(
    '%s passes the good page',
    async (check) => {
      expect(await outcome(check, GoodPage)).toBe('pass')
    },
  )
  it('every check has a page built to fail it', () => {
    expect(new Set(broken.map(([check]) => check))).toEqual(new Set(Object.keys(PAGE_CHECK_FUNCTIONS)))
  })
})

/** A module folder on disk, for the checks that read files. */
function folderWith(files: Record<string, string>): string {
  const folder = mkdtempSync(join(tmpdir(), 'conformance-'))
  for (const [path, content] of Object.entries(files)) {
    mkdirSync(join(folder, path, '..'), { recursive: true })
    writeFileSync(join(folder, path), content)
  }
  return folder
}
const folders: string[] = []
afterEach(() => {
  for (const folder of folders.splice(0)) rmSync(folder, { recursive: true, force: true })
})
const made = (files: Record<string, string>) => {
  const folder = folderWith(files)
  folders.push(folder)
  return folder
}

const manifest: ModuleEntry = {
  id: 'sample',
  name: 'Sample',
  version: '1',
  contributes: { pages: [{ id: 'main', path: '/sample' }], nav: [{ title: 'Sample', path: '/sample' }] },
  entry: null,
}

describe('manifest', () => {
  it('passes a manifest whose pages activate offers', async () => {
    await manifestCheck(manifest, { pages: { main: GoodPage } })
  })
  it('fails when activate leaves out a declared page', async () => {
    await expect(manifestCheck(manifest, { pages: {} })).rejects.toThrow(/does not offer/)
  })
  it('fails a manifest the registry cannot honour', async () => {
    const strayNav = { ...manifest, contributes: { ...manifest.contributes, nav: [{ title: 'X', path: '/nowhere' }] } }
    await expect(manifestCheck(strayNav, { pages: { main: GoodPage } })).rejects.toThrow(/could not honour/)
  })
})

describe('a contribution to a slot (step 3) is checked as a page is', () => {
  const contributing = {
    id: 'm',
    name: 'M',
    version: '1',
    entry: null,
    contributes: { into: [{ slot: 'inbox.tabs', id: 'tab', title: 'Tab' }] },
  } as unknown as ModuleEntry
  it('fails when activate leaves out a declared contribution', async () => {
    await expect(manifestCheck(contributing, { pages: {} })).rejects.toThrow(/declared contributions/)
  })
  it('passes when it offers it', async () => {
    await manifestCheck(contributing, { pages: {}, contributions: { tab: GoodPage } })
  })

  /** A TAB AS ELYSIUM'S SLOTS DRAW ONE: told how to end the session by a
   *  prop, not by the host values a page reads. */
  function GoodTab({ onSessionExpired }: { onSessionExpired: () => void }) {
    const { data, error } = useFetchOnce<unknown>(getCurrentUser, onSessionExpired)
    return (
      <AsyncPanel data={data} error={error}>
        {() => <p>signed in</p>}
      </AsyncPanel>
    )
  }
  /** Given the slot's onSessionExpired, and deaf to it. */
  const DeafTab: ComponentType<{ onSessionExpired: () => void }> = () => {
    const { data, error } = useFetchOnce<unknown>(getCurrentUser, () => {})
    return (
      <AsyncPanel data={data} error={error}>
        {() => <p>signed in</p>}
      </AsyncPanel>
    )
  }
  it("passes a tab that uses the slot's onSessionExpired, and fails one that ignores it", async () => {
    expect(await outcome('session-expired', asSlotted(GoodTab))).toBe('pass')
    expect(await outcome('session-expired', asSlotted(DeafTab))).toBe('fail')
  })
})

describe('layered-css', () => {
  it('passes stylesheets whose every rule is in a layer', async () => {
    await layeredCss(made({ 'src/a.css': '@layer app { .a { color: red } }' }))
  })
  it('fails one unlayered rule, however deep the file', async () => {
    await expect(layeredCss(made({ 'src/deep/b.css': '.b { color: red }' }))).rejects.toThrow(/b\.css: \.b/)
  })
})

describe('overrides', () => {
  const write = (checks: unknown) => made({ 'module.conformance.json': JSON.stringify({ checks }) })

  it('are none when the file is absent', () => {
    expect(readOverrides(made({}), ['main'])).toEqual({})
  })
  it('need a reason', () => {
    expect(() => readOverrides(write({ error: { level: 'todo' } }), ['main'])).toThrow(/needs a reason/)
  })
  it('refuse a check that does not exist, and a page the manifest does not declare', () => {
    expect(() => readOverrides(write({ eror: { level: 'off', reason: 'r' } }), ['main'])).toThrow(/no check called/)
    expect(() => readOverrides(write({ 'error@other': { level: 'off', reason: 'r' } }), ['main'])).toThrow(
      /does not declare/,
    )
  })
  it('refuse a level that is not one, and a replacement that names no test', () => {
    expect(() => readOverrides(write({ error: { level: 'warn', reason: 'r' } }), ['main'])).toThrow(/use todo/)
    expect(() => readOverrides(write({ error: { level: 'replaced', reason: 'r' } }), ['main'])).toThrow(/needs `by`/)
  })
  it('the narrowest wins', () => {
    const overrides = readOverrides(
      write({ error: { level: 'off', reason: 'all' }, 'error@main': { level: 'todo', reason: 'one' } }),
      ['main', 'other'],
    )
    expect(levelFor(overrides, 'error', 'main')).toMatchObject({ level: 'todo' })
    expect(levelFor(overrides, 'error', 'other')).toMatchObject({ level: 'off' })
    expect(levelFor(overrides, 'loading', 'main')).toEqual({ level: 'error' })
  })
})

describe('levels', () => {
  const where = { module: 'sample', check: 'error @ main', folder: '' }
  const passes = async () => {}
  const fails = async () => {
    throw new Error('the page failed')
  }

  it('error runs the check as it is', async () => {
    await expect(atLevel({ level: 'error' }, fails, where)!()).rejects.toThrow('the page failed')
  })
  it('off runs nothing', () => {
    expect(atLevel({ level: 'off', reason: 'r' }, fails, where)).toBeNull()
  })
  it('todo reports a failure without failing', async () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {})
    await atLevel({ level: 'todo', reason: 'r' }, fails, where)!()
    expect(warn).toHaveBeenCalledWith(expect.stringContaining('still fails'))
  })
  it('todo FAILS once the check passes, so the list of todos only shrinks', async () => {
    await expect(atLevel({ level: 'todo', reason: 'r' }, passes, where)!()).rejects.toThrow(/now passes/)
  })
  it('replaced passes only when the named test exists', async () => {
    const folder = made({ 'src/own.test.tsx': "it('shows its own error', () => {})" })
    const at = { ...where, folder }
    await atLevel({ level: 'replaced', reason: 'r', by: 'src/own.test.tsx::shows its own error' }, fails, at)!()
    await expect(
      atLevel({ level: 'replaced', reason: 'r', by: 'src/own.test.tsx::a test nobody wrote' }, fails, at)!(),
    ).rejects.toThrow(/no such test/)
    await expect(atLevel({ level: 'replaced', reason: 'r', by: 'src/gone.test.tsx::x' }, fails, at)!()).rejects.toThrow(
      /does not exist/,
    )
  })
})
