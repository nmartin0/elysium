import { act, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { CONTRACT_VERSION, MODULE_API_VERSION, type ModuleEntry, type ModuleFeed } from './contract'
import { ModuleLoader } from './moduleLoader'
import { ModulesPage } from './ModulesPage'

const entry = (id: string, extra: Partial<ModuleEntry> = {}): ModuleEntry => ({
  id,
  name: id.toUpperCase(),
  version: '2',
  api: '^1.0',
  contributes: { nav: [{ title: `${id} rail`, path: `/${id}` }] },
  entry: null,
  ...extra,
})
const feed = (modules: ModuleEntry[]): ModuleFeed => ({ contract: CONTRACT_VERSION, home: '/a', modules })
const row = (name: string) => screen.getByRole('rowheader', { name: new RegExp(name) }).closest('tr')!

describe('the Modules page', () => {
  it('lists every module the feed offers, in its order, with what the feed says of each', () => {
    render(<ModulesPage feed={feed([entry('a'), entry('b', { entry: '/b.js' })])} loader={new ModuleLoader()} />)

    expect(screen.getAllByRole('rowheader').map((cell) => cell.textContent)).toEqual(['A a', 'B b'])
    expect(within(row('A')).getByText('Built into the page')).toBeInTheDocument()
    expect(within(row('A')).getByText('Part of the page')).toBeInTheDocument()
    expect(within(row('B')).getByText('Its own bundle')).toBeInTheDocument()
    expect(within(row('B')).getByText('b rail')).toBeInTheDocument()
  })

  it('marks a pinned module', () => {
    render(<ModulesPage feed={feed([entry('sys', { pinned: true }), entry('b')])} loader={new ModuleLoader()} />)
    expect(within(row('SYS')).getByText('Pinned')).toBeInTheDocument()
    expect(within(row('B')).queryByText('Pinned')).not.toBeInTheDocument()
  })

  it('follows a module as it loads, and says why one failed', async () => {
    const good = entry('good', { entry: '/good.js' })
    const bad = entry('bad', { entry: '/bad.js' })
    const loader = new ModuleLoader(async (address) =>
      address === '/good.js' ? { activate: () => ({ pages: {} }) } : {},
    )
    render(<ModulesPage feed={feed([good, bad])} loader={loader} />)
    expect(within(row('GOOD')).getByText(/Not loaded yet/)).toBeInTheDocument()

    await act(async () => {
      await loader.load(good)
      await loader.load(bad).catch(() => {})
    })

    expect(within(row('GOOD')).getByText('Loaded')).toBeInTheDocument()
    expect(within(row('BAD')).getByText('Could not be loaded: its bundle does not export `activate`')).toBeInTheDocument()
  })

  it('says when a module that is not loaded will load', () => {
    render(
      <ModulesPage
        feed={feed([
          entry('start', { entry: '/s.js', activationEvents: ['onStartup'] }),
          entry('pal', { entry: '/p.js', activationEvents: ['onPalette'] }),
          entry('page', { entry: '/g.js' }),
        ])}
        loader={new ModuleLoader()}
      />,
    )
    expect(within(row('START')).getByText(/loads with the page/)).toBeInTheDocument()
    expect(within(row('PAL')).getByText(/or the palette, opens/)).toBeInTheDocument()
    expect(within(row('PAGE')).getByText(/loads when one of its pages opens/)).toBeInTheDocument()
  })
})

describe('the Modules page in safe mode', () => {
  it('says which modules safe mode left out, and leaves the pinned ones as they are', () => {
    render(
      <ModulesPage
        feed={feed([entry('sys', { pinned: true }), entry('b', { entry: '/b.js' })])}
        loader={new ModuleLoader()}
        safeMode
      />,
    )
    expect(within(row('B')).getByText('Off in safe mode')).toBeInTheDocument()
    expect(within(row('SYS')).getByText('Part of the page')).toBeInTheDocument()
  })
})

describe('the Modules page and the module API (step 4)', () => {
  it("says why a module this page cannot load is not loaded, whatever else is true of it", () => {
    render(
      <ModulesPage
        feed={feed([entry('new', { api: '^2.0' }), entry('old', { api: undefined }), entry('fine')])}
        loader={new ModuleLoader()}
        safeMode
      />,
    )
    expect(
      within(row('NEW')).getByText(`Not loaded: it needs the module API ^2.0, and this page offers ${MODULE_API_VERSION}`),
    )
      .toBeInTheDocument()
    expect(within(row('OLD')).getByText(/Not loaded: it names no module API version/)).toBeInTheDocument()
    expect(within(row('FINE')).getByText('Off in safe mode')).toBeInTheDocument()
  })
})
