import { describe, expect, it, vi } from 'vitest'
import { CONTRACT_VERSION, type ModuleEntry } from './contract'
import { enterSafeMode, leaveSafeMode, safeFeed, safeModeAtLoad, type SafeModeHost } from './safeMode'

function host(search = '', stored: string | null = null, refuse = false) {
  const store = new Map<string, string>()
  if (stored !== null) store.set('shell.safeMode', stored)
  const storage = {
    getItem: vi.fn((k: string) => {
      if (refuse) throw new Error('denied')
      return store.get(k) ?? null
    }),
    setItem: vi.fn((k: string, v: string) => {
      if (refuse) throw new Error('denied')
      store.set(k, v)
    }),
    removeItem: vi.fn((k: string) => void store.delete(k)),
  }
  const h: SafeModeHost = {
    location: { search, pathname: '/browse', hash: '#x', assign: vi.fn() },
    history: { state: null, replaceState: vi.fn() },
    storage,
  }
  return { h, store }
}

describe('safe mode at load', () => {
  it('is on when the address asks, remembered for the tab, and the marker taken out of the address', () => {
    const { h, store } = host('?safe&type=Customer')
    expect(safeModeAtLoad(h)).toBe(true)
    expect(store.get('shell.safeMode')).toBe('1')
    expect(h.history.replaceState).toHaveBeenCalledWith(null, '', '/browse?type=Customer#x')
  })

  it('carries on in the same tab without the marker', () => {
    expect(safeModeAtLoad(host('', '1').h)).toBe(true)
  })

  it('is off otherwise', () => {
    const { h } = host('?type=Customer')
    expect(safeModeAtLoad(h)).toBe(false)
    expect(h.history.replaceState).not.toHaveBeenCalled()
  })

  it('still works for this load when storage is refused', () => {
    expect(safeModeAtLoad(host('?safe', null, true).h)).toBe(true)
    expect(safeModeAtLoad(host('', null, true).h)).toBe(false)
  })
})

describe('entering and leaving', () => {
  it('both reload the page, because a module once imported stays until a reload', () => {
    const entering = host()
    enterSafeMode(entering.h)
    expect(entering.h.location.assign).toHaveBeenCalledWith('/?safe')

    const leaving = host('', '1')
    leaveSafeMode(leaving.h)
    expect(leaving.store.has('shell.safeMode')).toBe(false)
    expect(leaving.h.location.assign).toHaveBeenCalledWith('/')
  })
})

describe('the feed in safe mode', () => {
  const module = (id: string, path: string, pinned?: boolean): ModuleEntry => ({
    id,
    name: id,
    version: '1',
    contributes: { pages: [{ id: 'main', path }] },
    entry: null,
    pinned,
  })
  const feed = (home: string, modules: ModuleEntry[]) => ({ contract: CONTRACT_VERSION, home, modules })

  it('holds only the pinned modules', () => {
    const safe = safeFeed(feed('/q', [module('q', '/q'), module('sys', '/sys', true), module('b', '/b', false)]))
    expect(safe.modules.map((m) => m.id)).toEqual(['sys'])
  })

  it("moves home to a pinned module's page when home is not one", () => {
    expect(safeFeed(feed('/q', [module('q', '/q'), module('sys', '/sys', true)])).home).toBe('/sys')
    expect(safeFeed(feed('/sys', [module('sys', '/sys', true)])).home).toBe('/sys')
  })

  it('offers nothing to someone offered no pinned module, keeping home as it was', () => {
    const safe = safeFeed(feed('/q', [module('q', '/q')]))
    expect(safe.modules).toEqual([])
    expect(safe.home).toBe('/q')
  })
})
