import { render, screen, within } from '@testing-library/react'
import { Suspense, useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ModuleEntry } from './contract'
import { ModuleLoader, STYLE_ATTRIBUTE, type Importer, type ModuleContext } from './moduleLoader'

const MODULE: ModuleEntry = {
  id: 'graph',
  name: 'Graph',
  version: '1',
  entry: '/modules/graph/index.js',
  styles: ['/modules/graph/index.css'],
  contributes: { pages: [{ id: 'main', path: '/graph' }] },
}

function Counter() {
  const [n, setN] = useState(0)
  return <button onClick={() => setN(n + 1)}>count {n}</button>
}

function bundle(extra: Record<string, unknown> = {}) {
  const deactivate = vi.fn()
  const activate = vi.fn((_: ModuleContext) => ({ pages: { main: Counter } }))
  return { exports: { activate, deactivate, ...extra }, activate, deactivate }
}

function show(loader: ModuleLoader, module: ModuleEntry, pageId = 'main') {
  const Page = loader.page(module, pageId)
  return render(
    <Suspense fallback={<p>loading</p>}>
      <Page />
    </Suspense>,
  )
}

afterEach(() => {
  for (const link of document.querySelectorAll(`link[${STYLE_ATTRIBUTE}]`)) link.remove()
})

const styleLinks = (id: string) => document.querySelectorAll(`link[${STYLE_ATTRIBUTE}="${id}"]`)

describe('ModuleLoader', () => {
  it("renders a module's page from its bundle, activating it with its id and version", async () => {
    const b = bundle()
    const importer: Importer = vi.fn(async () => b.exports)
    const loader = new ModuleLoader(importer)

    show(loader, MODULE)

    expect(await screen.findByRole('button', { name: 'count 0' })).toBeInTheDocument()
    expect(importer).toHaveBeenCalledWith('/modules/graph/index.js')
    expect(b.activate).toHaveBeenCalledWith({ id: 'graph', version: '1' })
  })

  it('loads a bundle once however many of its pages are asked for', async () => {
    const b = bundle()
    const importer = vi.fn(async () => b.exports)
    const loader = new ModuleLoader(importer)

    await loader.load(MODULE)
    await loader.load(MODULE)

    expect(importer).toHaveBeenCalledTimes(1)
    expect(b.activate).toHaveBeenCalledTimes(1)
  })

  it('gives the same component for the same page, so a re-render never remounts it', () => {
    const loader = new ModuleLoader(async () => bundle().exports)

    expect(loader.page(MODULE, 'main')).toBe(loader.page(MODULE, 'main'))
  })

  it("adds the module's stylesheets when it loads, and removes them and deactivates it when it unloads", async () => {
    const b = bundle()
    const loader = new ModuleLoader(async () => b.exports)

    await loader.load(MODULE)
    expect(styleLinks('graph')).toHaveLength(1)
    expect(styleLinks('graph')[0]?.getAttribute('href')).toBe('/modules/graph/index.css')

    loader.retain([])

    expect(styleLinks('graph')).toHaveLength(0)
    expect(b.deactivate).toHaveBeenCalledTimes(1)
    expect(loader.loadedIds()).toEqual([])
  })

  it('says which module failed and why, instead of crashing the shell', async () => {
    const loader = new ModuleLoader(async () => {
      throw new Error('404 for the bundle')
    })

    show(loader, MODULE)

    expect(await screen.findByRole('alert')).toHaveTextContent(/graph could not be loaded: 404 for the bundle/)
    expect(styleLinks('graph')).toHaveLength(0)
  })

  it('refuses a bundle without `activate`', async () => {
    const loader = new ModuleLoader(async () => ({}))

    show(loader, MODULE)

    expect(await screen.findByRole('alert')).toHaveTextContent(/does not export `activate`/)
  })

  it('says so when the bundle offers no page by that id', async () => {
    const loader = new ModuleLoader(async () => bundle().exports)

    show(loader, MODULE, 'missing')

    expect(await screen.findByRole('alert')).toHaveTextContent(/offers no page called missing/)
  })

  it('forgets a failed load, so the next explicit load tries again', async () => {
    const b = bundle()
    const importer = vi.fn<Importer>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(b.exports)
    const loader = new ModuleLoader(importer)

    await expect(loader.load(MODULE)).rejects.toThrow('offline')
    await Promise.resolve()
    await expect(loader.load(MODULE)).resolves.toHaveProperty('pages')
    expect(importer).toHaveBeenCalledTimes(2)
  })

  it('replaces a loaded module when the feed brings it at a new address', async () => {
    const first = bundle()
    const second = bundle()
    const importer = vi.fn<Importer>().mockResolvedValueOnce(first.exports).mockResolvedValueOnce(second.exports)
    const loader = new ModuleLoader(importer)

    await loader.load(MODULE)
    await loader.load({ ...MODULE, version: '2', entry: '/modules/graph/index.js?v=2' })

    expect(importer).toHaveBeenLastCalledWith('/modules/graph/index.js?v=2')
    expect(first.deactivate).toHaveBeenCalledTimes(1)
    expect(second.activate).toHaveBeenCalledWith({ id: 'graph', version: '2' })
    expect(styleLinks('graph')).toHaveLength(1)
  })

  it('gives a new component for a new address, since it is new code', () => {
    const loader = new ModuleLoader(async () => bundle().exports)

    expect(loader.page(MODULE, 'main')).not.toBe(loader.page({ ...MODULE, entry: '/other.js' }, 'main'))
  })

  it('never activates a module unloaded while its bundle was still arriving', async () => {
    const b = bundle()
    let arrive: (value: unknown) => void = () => {}
    const loader = new ModuleLoader(() => new Promise((resolve) => (arrive = resolve)))

    const loading = loader.load(MODULE)
    loader.retain([])
    arrive(b.exports)

    await expect(loading).rejects.toThrow(/unloaded while loading/)
    expect(b.activate).not.toHaveBeenCalled()
    expect(styleLinks('graph')).toHaveLength(0)
  })

  it('deactivates, exactly once, a module unloaded while its activate was running', async () => {
    let finish: (value: { pages: Record<string, typeof Counter> }) => void = () => {}
    const deactivate = vi.fn()
    const exports = { activate: () => new Promise((resolve) => (finish = resolve)), deactivate }
    const loader = new ModuleLoader(async () => exports)

    const loading = loader.load(MODULE)
    await Promise.resolve()
    await Promise.resolve()
    loader.retain([])
    finish({ pages: { main: Counter } })

    await expect(loading).rejects.toThrow(/unloaded while loading/)
    expect(deactivate).toHaveBeenCalledTimes(1)
  })

  it('keeps a failed page as it is until the feed is next applied, then tries again', async () => {
    const b = bundle()
    const importer = vi.fn<Importer>().mockRejectedValueOnce(new Error('offline')).mockResolvedValue(b.exports)
    const loader = new ModuleLoader(importer)
    const failedPage = loader.page(MODULE, 'main')
    const FailedPage = failedPage
    render(
      <Suspense fallback={<p>loading</p>}>
        <FailedPage />
      </Suspense>,
    )
    await screen.findByRole('alert')

    // A RE-RENDER asks again, and gets the same failed page: no retry, no
    // remount.
    expect(loader.page(MODULE, 'main')).toBe(failedPage)
    expect(importer).toHaveBeenCalledTimes(1)

    loader.retain(['graph'])

    expect(loader.page(MODULE, 'main')).not.toBe(failedPage)
  })
})

describe("a module's status, for the module manager", () => {
  it('goes from not loaded, through loading, to loaded, telling subscribers each time', async () => {
    let finish: (exports: unknown) => void = () => {}
    const loader = new ModuleLoader(() => new Promise((resolve) => (finish = resolve)))
    const told = vi.fn()
    loader.subscribe(told)
    expect(loader.status(MODULE)).toEqual({ state: 'not-loaded' })

    const loading = loader.load(MODULE)
    expect(loader.status(MODULE)).toEqual({ state: 'loading' })
    finish(bundle().exports)
    await loading

    expect(loader.status(MODULE)).toEqual({ state: 'loaded' })
    expect(told).toHaveBeenCalledTimes(2)
  })

  it('says why a load failed, until the feed is applied again', async () => {
    const loader = new ModuleLoader(async () => ({}))
    await loader.load(MODULE).catch(() => {})

    expect(loader.status(MODULE)).toEqual({ state: 'failed', reason: 'its bundle does not export `activate`' })
    loader.retain([MODULE.id])
    expect(loader.status(MODULE)).toEqual({ state: 'not-loaded' })
  })

  it('a module with no bundle is part of the page', () => {
    expect(new ModuleLoader().status({ ...MODULE, entry: null })).toEqual({ state: 'built-in' })
  })

  it('unloading is a change too, and a stopped subscriber hears nothing more', async () => {
    const loader = new ModuleLoader(async () => bundle().exports)
    await loader.load(MODULE)
    const told = vi.fn()
    const stop = loader.subscribe(told)
    loader.unload(MODULE.id)
    expect(told).toHaveBeenCalledTimes(1)
    expect(loader.status(MODULE)).toEqual({ state: 'not-loaded' })
    stop()
    await loader.load(MODULE)
    expect(told).toHaveBeenCalledTimes(1)
  })
})

describe('a module that could not be loaded', () => {
  it('offers safe mode, as a link -- it never switches on by itself', async () => {
    const loader = new ModuleLoader(async () => ({}))
    show(loader, MODULE)
    const alert = await screen.findByRole('alert')
    expect(within(alert).getByRole('link', { name: 'reload it in safe mode' })).toHaveAttribute('href', '/?safe')
  })
})
