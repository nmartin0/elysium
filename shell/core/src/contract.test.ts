// The module API a page offers and a module needs (BLOCKING.md item 3,
// step 4): VS Code's `engines.vscode`, "^1.0" meaning 1.0 or any later
// 1.x, and nothing loaded that asks for more.
import { describe, expect, it } from 'vitest'
import { apiRefusal, compatibleFeed, CONTRACT_VERSION, MODULE_API_VERSION, type ModuleEntry } from './contract'

const module = (id: string, api: string | undefined, path = `/${id}`): ModuleEntry => ({
  id,
  name: id,
  version: '1',
  api,
  entry: null,
  contributes: { pages: [{ id: 'main', path }] },
})

describe('whether a page can load a module', () => {
  it.each([
    ['^1.0', '1.0'],
    ['^1.0', '1.3'],
    ['^1.2', '1.2'],
    ['^0.4', '0.9'],
  ])('a module needing %s loads on a page offering %s', (api, offered) => {
    expect(apiRefusal({ api }, offered)).toBeNull()
  })

  it.each([
    ['^1.3', '1.2', 'it needs the module API ^1.3, and this page offers 1.2'],
    ['^2.0', '1.9', 'it needs the module API ^2.0, and this page offers 1.9'],
    ['^1.0', '2.0', 'it needs the module API ^1.0, and this page offers 2.0'],
  ])('one needing %s does not on a page offering %s', (api, offered, said) => {
    expect(apiRefusal({ api }, offered)).toBe(said)
  })

  it('one naming none does not, and says what to write', () => {
    expect(apiRefusal({ api: undefined })).toMatch(/names no module API version.*"api": "\^1\.0"/)
  })

  it.each(['1.0', '^1', '>=1.0', '^1.0.0', '^01.0', ' ^1.0'])('one writing %j does not, and says so', (api) => {
    expect(apiRefusal({ api })).toBe(`its module.json's \`api\` is "${api}", not a version such as "^1.0"`)
  })

  it('this page offers 1.1, so a module built for 1.0 still loads, and one for 1.2 does not', () => {
    expect(MODULE_API_VERSION).toBe('1.1')
    expect(apiRefusal({ api: '^1.0' })).toBeNull()
    expect(apiRefusal({ api: '^1.1' })).toBeNull()
    expect(apiRefusal({ api: '^1.2' })).toMatch(/needs the module API \^1\.2/)
  })
})

describe('the feed as a page can load it', () => {
  it('leaves out what it cannot load, and moves home if home was left out', () => {
    const feed = {
      contract: CONTRACT_VERSION,
      home: '/new',
      modules: [module('new', '^9.0'), module('fine', '^1.0'), module('bare', undefined)],
    }

    const loadable = compatibleFeed(feed)

    expect(loadable.modules.map((m) => m.id)).toEqual(['fine'])
    expect(loadable.home).toBe('/fine')
  })

  it('is the same feed when everything loads', () => {
    const feed = { contract: CONTRACT_VERSION, home: '/a', modules: [module('a', '^1.0')] }

    expect(compatibleFeed(feed)).toBe(feed)
  })
})
