/**
 * The frame's own contract, with nothing of any host in it: what it
 * draws from the props it is given, and the behaviour it owns. Elysium's
 * ui/src/Shell.test.tsx tests the frame as Elysium composes it.
 */
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { lazy, useEffect, useState, type ComponentType } from 'react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Command } from './commands'
import type { ModuleEntry } from './contract'
import type { PaletteHook } from './palette'
import type { BadgeHook } from './badges'
import { Frame, type FrameNavEntry, type FrameProps } from './Frame'

const KEY = 'test.railCollapsed'
const NAV: FrameNavEntry[] = [
  { title: 'Alpha', path: '/alpha', subject: 'Work' },
  { title: 'Beta', path: '/beta', subject: 'Work' },
  { title: 'Gamma', path: '/gamma', subject: 'Settings' },
]

function Where() {
  return <p data-testid="at">{useLocation().pathname}</p>
}

function narrow(matches: boolean) {
  let current = matches
  let onChange: (() => void) | null = null
  vi.stubGlobal(
    'matchMedia',
    (media: string) =>
      ({
        get matches() {
          return current
        },
        media,
        addEventListener: (_: string, handler: () => void) => (onChange = handler),
        removeEventListener: () => {},
      }) as unknown as MediaQueryList,
  )
  return {
    resize(next: boolean) {
      current = next
      act(() => onChange?.())
    },
  }
}

function renderFrame(props: Partial<FrameProps> = {}, page: ComponentType = Where, at = '/alpha') {
  const Page = page
  return render(
    <MemoryRouter initialEntries={[at]}>
      <Routes>
        <Route
          element={
            <Frame
              nav={NAV}
              brand="Product"
              iconFor={() => 'cube'}
              fallback={<p>loading the page</p>}
              storageKey={KEY}
              {...props}
            />
          }
        >
          <Route path="*" element={<Page />} />
        </Route>
      </Routes>
    </MemoryRouter>,
  )
}

const rail = () => document.querySelector('.app__sidebar') as HTMLElement
const isCollapsed = () => document.querySelector('.app-frame')!.classList.contains('app-frame--sidebar-collapsed')

beforeEach(() => {
  window.localStorage.clear()
  narrow(false)
})
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('what the frame draws from what it is given', () => {
  it('the brand and the actions in the header, the page in the content area', () => {
    renderFrame({ actions: <button type="button">Account</button> })
    const header = document.querySelector('header')!
    expect(within(header).getByRole('heading', { name: 'Product' })).toBeInTheDocument()
    expect(within(header).getByRole('button', { name: 'Account' })).toBeInTheDocument()
    expect(within(document.querySelector('main')!).getByTestId('at')).toHaveTextContent('/alpha')
  })

  it('the rail holds the entries in order, under a heading wherever the subject changes', () => {
    renderFrame()
    // By the DOM: the headings are role="presentation", so no role query
    // sees the list as a reader of the page does.
    const items = [...rail().querySelectorAll('.app__nav > li')].map((li) => li.textContent)
    expect(items).toEqual(['Work', 'Alpha', 'Beta', 'Settings', 'Gamma'])
  })

  it('an entry with no subject gets no heading', () => {
    renderFrame({ nav: [{ title: 'Alpha', path: '/alpha' }] })
    expect(rail().querySelectorAll('.app__nav-subject')).toHaveLength(0)
  })

  it('marks the page you are on, and only it', () => {
    renderFrame({}, Where, '/beta')
    expect(screen.getByRole('menuitem', { name: 'Beta' })).toHaveAttribute('aria-current', 'page')
    expect(screen.getByRole('menuitem', { name: 'Alpha' })).not.toHaveAttribute('aria-current')
  })

  it('asks the host for each entry\'s icon', () => {
    const iconFor = vi.fn((_path: string) => 'cube' as const)
    renderFrame({ iconFor })
    expect(iconFor.mock.calls.map(([path]) => path)).toEqual(expect.arrayContaining(['/alpha', '/beta', '/gamma']))
  })

  it('navigates in the page, without reloading it', () => {
    renderFrame()
    const click = fireEvent.click(screen.getByRole('menuitem', { name: 'Gamma' }))
    expect(click).toBe(false) // default prevented: no full page load
    expect(screen.getByTestId('at')).toHaveTextContent('/gamma')
  })

  it('draws the host\'s overlays', () => {
    renderFrame({ overlays: <div role="dialog" aria-label="Help" /> })
    expect(screen.getByRole('dialog', { name: 'Help' })).toBeInTheDocument()
  })
})

describe('collapsing the rail', () => {
  it('starts open on a wide screen, with nothing remembered', () => {
    renderFrame()
    expect(isCollapsed()).toBe(false)
  })

  it('starts collapsed on a narrow screen', () => {
    narrow(true)
    renderFrame()
    expect(isCollapsed()).toBe(true)
  })

  it('remembers the choice under the key the host gave', () => {
    renderFrame()
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(window.localStorage.getItem(KEY)).toBe('true')
  })

  it('a remembered choice wins over the screen width', () => {
    window.localStorage.setItem(KEY, 'false')
    narrow(true)
    renderFrame()
    expect(isCollapsed()).toBe(false)
  })

  it('Ctrl+B and Cmd+B toggle it, every time, not only the first', () => {
    renderFrame()
    const seen: boolean[] = []
    for (const key of [{ ctrlKey: true }, { metaKey: true }, { ctrlKey: true }, { metaKey: true }]) {
      fireEvent.keyDown(window, { key: 'b', ...key })
      seen.push(isCollapsed())
    }
    expect(seen).toEqual([true, false, true, false])
  })

  it('a bare b is somebody typing', () => {
    renderFrame()
    fireEvent.keyDown(window, { key: 'b' })
    expect(isCollapsed()).toBe(false)
  })

  it('narrowing the window closes it without storing that; widening restores the stored choice', () => {
    const screenSize = narrow(false)
    renderFrame()
    screenSize.resize(true)
    expect(isCollapsed()).toBe(true)
    expect(window.localStorage.getItem(KEY)).toBeNull()
    screenSize.resize(false)
    expect(isCollapsed()).toBe(false)
  })

  it('on a narrow screen, navigating closes an expanded rail; on a wide one it does not', () => {
    window.localStorage.setItem(KEY, 'false')
    narrow(true)
    renderFrame()
    expect(isCollapsed()).toBe(false) // the stored choice, untouched by mounting
    fireEvent.click(screen.getByRole('menuitem', { name: 'Beta' }))
    expect(isCollapsed()).toBe(true)
  })

  it('a collapsed rail titles each entry, so its name shows on hover; an open one does not repeat its label', () => {
    renderFrame()
    expect(screen.getByRole('menuitem', { name: 'Alpha' })).not.toHaveAttribute('title')
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(screen.getByRole('menuitem', { name: 'Alpha' })).toHaveAttribute('title', 'Alpha')
  })

  it('stays usable when storage refuses', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    renderFrame()
    fireEvent.click(screen.getByRole('button', { name: 'Collapse sidebar' }))
    expect(isCollapsed()).toBe(true)
  })
})

describe('the palette', () => {
  const run = vi.fn()
  const command = (label: string): Command => ({ id: label, label, group: 'Host', run })

  it('opens on Cmd-K and Ctrl-K, and tells the host each time it opens', () => {
    const onPaletteOpen = vi.fn()
    renderFrame({ onPaletteOpen })
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    fireEvent.keyDown(window, { key: 'k', metaKey: true })
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(onPaletteOpen).toHaveBeenCalledTimes(1)
  })

  it('lists the host\'s commands either side of the frame\'s own navigation', () => {
    renderFrame({ commands: { before: [command('First')], after: [command('Last')] } })
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    const labels = within(screen.getByRole('dialog'))
      .getAllByRole('option')
      .map((option) => option.textContent)
    expect(labels[0]).toContain('First')
    expect(labels.at(-1)).toContain('Last')
    expect(labels.join(' ')).toMatch(/First.*Alpha.*Beta.*Gamma.*Last/)
  })

  it('a navigation command goes where its rail entry goes', () => {
    renderFrame()
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('option', { name: /Gamma/ }))
    expect(screen.getByTestId('at')).toHaveTextContent('/gamma')
  })
})

describe('while a page loads', () => {
  it('the host\'s fallback fills the content area, and the frame stays drawn', () => {
    const Never = lazy(() => new Promise<{ default: ComponentType }>(() => {}))
    renderFrame({}, Never)
    expect(within(document.querySelector('main')!).getByText('loading the page')).toBeInTheDocument()
    expect(screen.getByRole('menuitem', { name: 'Alpha' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Product' })).toBeInTheDocument()
  })
})

describe("modules' palette commands", () => {
  const module = (id: string, events: string[] = ['onPalette']): ModuleEntry => ({
    id,
    name: id,
    version: '1',
    contributes: {},
    entry: null,
    activationEvents: events,
  })
  const cmd = (label: string): Command => ({ id: label, label, group: 'Module', run: () => {} })
  /** The host's activator for modules whose code is only a palette hook. */
  const viaPalette = (feed: ModuleEntry[], resolve: (module: ModuleEntry) => unknown) => ({
    feed,
    activate: async (m: ModuleEntry) => {
      const usePalette = (await resolve(m)) as PaletteHook | undefined
      return usePalette && { usePalette }
    },
  })
  const openPalette = async () => {
    fireEvent.keyDown(window, { key: 'k', ctrlKey: true })
    await act(async () => {})
  }
  const labels = () =>
    within(screen.getByRole('dialog'))
      .getAllByRole('option')
      .map((option) => option.textContent ?? '')

  it("loads a module's code only once the palette opens, then lists its commands around navigation", async () => {
    const resolve = vi.fn(() => (() => ({ before: [cmd('Act here')], after: [cmd('Module later')] })) as PaletteHook)
    renderFrame({
      modules: viaPalette([module('m')], resolve),
      commands: { before: [cmd('Host first')], after: [cmd('Host last')] },
    })
    expect(resolve).not.toHaveBeenCalled()

    await openPalette()

    expect(resolve).toHaveBeenCalledTimes(1)
    expect(labels().join(' ')).toMatch(/Act here.*Host first.*Alpha.*Gamma.*Module later.*Host last/)
  })

  it('asks nothing of a module that does not activate on the palette', async () => {
    const resolve = vi.fn(() => (() => ({ before: [cmd('Never')] })) as PaletteHook)
    renderFrame({ modules: viaPalette([module('m', [])], resolve) })
    await openPalette()
    expect(resolve).not.toHaveBeenCalled()
    expect(labels().join(' ')).not.toContain('Never')
  })

  it("tells a module's hook whether the palette is open, so it can load what it lists then", async () => {
    const usePalette: PaletteHook = ({ open }) => {
      const [loaded, setLoaded] = useState<string[]>([])
      useEffect(() => {
        if (open) setLoaded(['Loaded on opening'])
      }, [open])
      return { after: loaded.map(cmd) }
    }
    renderFrame({ modules: viaPalette([module('m')], () => usePalette) })
    await openPalette()
    expect(labels().join(' ')).toContain('Loaded on opening')
  })

  it('a module whose code fails to load leaves the palette working, and is asked again next time', async () => {
    const resolve = vi.fn(() => Promise.reject(new Error('no bundle')))
    renderFrame({ modules: viaPalette([module('m')], resolve) })
    await openPalette()
    expect(labels().join(' ')).toContain('Alpha')
    fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Escape' })
    await act(async () => {})
    await openPalette()
    expect(resolve).toHaveBeenCalledTimes(2)
  })

  it("adds a module's suggestions to what was typed", async () => {
    const usePalette: PaletteHook = () => ({ suggest: (query) => [cmd(`Find ${query}`)] })
    renderFrame({ modules: viaPalette([module('m')], () => usePalette) })
    await openPalette()
    fireEvent.change(screen.getByLabelText('Search commands'), { target: { value: 'ada' } })
    expect(labels().join(' ')).toContain('Find ada')
  })

  it('drops the commands of a module the feed stops offering', async () => {
    const usePalette: PaletteHook = () => ({ after: [cmd('From m')] })
    const resolve = () => usePalette
    const view = renderFrame({ modules: viaPalette([module('m')], resolve) })
    await openPalette()
    expect(labels().join(' ')).toContain('From m')
    view.rerender(
      <MemoryRouter initialEntries={['/alpha']}>
        <Routes>
          <Route
            element={
              <Frame
                nav={NAV}
                brand="Product"
                iconFor={() => 'cube'}
                fallback={null}
                storageKey={KEY}
                modules={viaPalette([], resolve)}
              />
            }
          >
            <Route path="*" element={<Where />} />
          </Route>
        </Routes>
      </MemoryRouter>,
    )
    await act(async () => {})
    expect(labels().join(' ')).not.toContain('From m')
  })
})

describe('badges on rail entries', () => {
  const inbox = (events: string[] = ['onStartup'], nav = [{ title: 'Beta', path: '/beta' }]): ModuleEntry => ({
    id: 'b',
    name: 'B',
    version: '1',
    contributes: { nav },
    entry: null,
    activationEvents: events,
  })
  const withBadges = (feed: ModuleEntry[], useBadges: BadgeHook) => ({ feed, activate: () => ({ useBadges }) })
  const settle = () => act(async () => new Promise((resolve) => setTimeout(resolve, 0)))
  const badgeOn = (name: RegExp) => screen.getByRole('menuitem', { name }).querySelector('.app__nav-badge')

  it('draws the count a startup module gives its own entry, and announces it after the name', async () => {
    renderFrame({ modules: withBadges([inbox()], () => ({ '/beta': { count: 3, label: '3 waiting' } })) })
    await settle()
    expect(screen.getByRole('menuitem', { name: 'Beta, 3 waiting' })).toBeInTheDocument()
    expect(badgeOn(/Beta/)).toHaveTextContent('3')
  })

  it('without the palette ever opening -- it is there from the start', async () => {
    const activate = vi.fn(() => ({ useBadges: () => ({ '/beta': { count: 1, label: '1 waiting' } }) }))
    renderFrame({ modules: { feed: [inbox()], activate } })
    await settle()
    expect(activate).toHaveBeenCalledTimes(1)
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
  })

  it('shows a large count as 99+', async () => {
    renderFrame({ modules: withBadges([inbox()], () => ({ '/beta': { count: 140, label: '140 waiting' } })) })
    await settle()
    expect(badgeOn(/Beta/)).toHaveTextContent('99+')
  })

  it('draws nothing for zero', async () => {
    renderFrame({ modules: withBadges([inbox()], () => ({ '/beta': { count: 0, label: 'none waiting' } })) })
    await settle()
    expect(screen.getByRole('menuitem', { name: 'Beta' })).toBeInTheDocument()
    expect(document.querySelector('.app__nav-badge')).toBeNull()
  })

  it("ignores a badge for another module's entry", async () => {
    renderFrame({ modules: withBadges([inbox()], () => ({ '/alpha': { count: 5, label: '5 waiting' } })) })
    await settle()
    expect(document.querySelector('.app__nav-badge')).toBeNull()
  })

  it('activates nothing for a module that does not name onStartup', async () => {
    const activate = vi.fn(() => ({ useBadges: () => ({ '/beta': { count: 2, label: '2 waiting' } }) }))
    renderFrame({ modules: { feed: [inbox([])], activate } })
    await settle()
    expect(activate).not.toHaveBeenCalled()
    expect(document.querySelector('.app__nav-badge')).toBeNull()
  })

  it('follows the count as it changes', async () => {
    let setCount: (n: number) => void = () => {}
    const useBadges: BadgeHook = () => {
      const [count, set] = useState(1)
      setCount = set
      return { '/beta': { count, label: `${count} waiting` } }
    }
    renderFrame({ modules: withBadges([inbox()], useBadges) })
    await settle()
    act(() => setCount(4))
    expect(screen.getByRole('menuitem', { name: 'Beta, 4 waiting' })).toBeInTheDocument()
  })
})
