import { describe, expect, it } from 'vitest'
import { CONTRACT_VERSION, FeedError, checkFeed, type ModuleFeed } from './contract'
import { buildRegistry } from './registry'

function feed(modules: ModuleFeed['modules']): ModuleFeed {
  return { contract: CONTRACT_VERSION, home: '/a', modules }
}

describe('checkFeed', () => {
  it('accepts a feed in this contract', () => {
    const raw = { contract: CONTRACT_VERSION, home: '/a', modules: [] }

    expect(checkFeed(raw)).toEqual(raw)
  })

  it('refuses another contract version by name rather than half-reading it', () => {
    expect(() => checkFeed({ contract: 99, home: '/a', modules: [] })).toThrow(/contract 99/)
  })

  it('refuses two modules with one id', () => {
    const module = { id: 'm', name: 'M', version: '1', contributes: {}, entry: null }

    expect(() => checkFeed({ contract: CONTRACT_VERSION, home: '/a', modules: [module, module] })).toThrow(FeedError)
  })
})

describe('buildRegistry', () => {
  it('mounts each page, and lists the rail in feed order', () => {
    const registry = buildRegistry(
      feed([
        {
          id: 'one',
          name: 'One',
          version: '1',
          entry: null,
          contributes: { pages: [{ id: 'main', path: '/one' }], nav: [{ title: 'One', path: '/one', subject: 'A' }] },
        },
        {
          id: 'two',
          name: 'Two',
          version: '1',
          entry: null,
          contributes: { pages: [{ id: 'main', path: '/two' }], nav: [{ title: 'Two', path: '/two' }] },
        },
      ]),
    )

    expect(registry.pages.map((p) => [p.moduleId, p.path])).toEqual([
      ['one', '/one'],
      ['two', '/two'],
    ])
    expect(registry.nav.map((n) => n.title)).toEqual(['One', 'Two'])
    expect(registry.problems).toEqual([])
  })

  it('keeps each subject in one run of the rail, in order of first appearance', () => {
    const module = (id: string, subject: string) => ({
      id,
      name: id,
      version: '1',
      entry: null,
      contributes: { pages: [{ id: 'p', path: `/${id}` }], nav: [{ title: id, path: `/${id}`, subject }] },
    })
    const registry = buildRegistry(feed([module('a', 'Objects'), module('b', 'Settings'), module('c', 'Objects')]))

    expect(registry.nav.map((n) => n.title)).toEqual(['a', 'c', 'b'])
  })

  it('gives a path to the first module that claims it, and says which lost', () => {
    const registry = buildRegistry(
      feed([
        { id: 'first', name: 'F', version: '1', entry: null, contributes: { pages: [{ id: 'p', path: '/x' }] } },
        { id: 'second', name: 'S', version: '1', entry: null, contributes: { pages: [{ id: 'p', path: '/x' }] } },
      ]),
    )

    expect(registry.pages).toEqual([{ moduleId: 'first', pageId: 'p', path: '/x' }])
    expect(registry.problems).toEqual(["second: the page /x is already first's, so it is not mounted"])
  })

  it('refuses a rail entry leading to a page the module does not own', () => {
    const registry = buildRegistry(
      feed([
        {
          id: 'm',
          name: 'M',
          version: '1',
          entry: null,
          contributes: { pages: [{ id: 'p', path: '/m' }], nav: [{ title: 'Elsewhere', path: '/admin' }] },
        },
      ]),
    )

    expect(registry.nav).toEqual([])
    expect(registry.problems[0]).toMatch(/Elsewhere leads to \/admin/)
  })

  it('keeps an old address leading to its new one, unless a page holds it', () => {
    const registry = buildRegistry(
      feed([
        { id: 'a', name: 'A', version: '1', entry: null, contributes: { pages: [{ id: 'p', path: '/old' }] } },
        {
          id: 'b',
          name: 'B',
          version: '1',
          entry: null,
          contributes: {
            pages: [{ id: 'p', path: '/new' }],
            redirects: [
              { from: '/old', to: '/new' },
              { from: '/older', to: '/new' },
            ],
          },
        },
      ]),
    )

    expect(registry.redirects).toEqual([{ from: '/older', to: '/new' }])
    expect(registry.problems).toEqual(["b: /old is a's page, so it is not redirected"])
  })
})
