import { render, screen } from '@testing-library/react'
import { Suspense, type ComponentType } from 'react'
import { describe, expect, it, vi } from 'vitest'
import type { FrameModules, ModuleCode } from './activation'
import type { ModuleEntry, SlotContribution } from './contract'
import { SlotsProvider, useSlot } from './slots'

const module = (id: string, extra: Partial<ModuleEntry['contributes']> = {}): ModuleEntry => ({
  id,
  name: id,
  version: '1',
  entry: null,
  contributes: extra,
})
const into = (id: string, title = id.toUpperCase()): SlotContribution => ({ slot: 'owner.tabs', id, title })

/** An owner page drawing its slot as a list, each item given `who`. */
function Owner() {
  const items = useSlot<{ who: string }>('owner.tabs')
  return (
    <ul>
      {items.map(({ id, title, Component }) => (
        <li key={id}>
          {title}:{' '}
          <Suspense fallback={<span>loading</span>}>
            <Component who="ada" />
          </Suspense>
        </li>
      ))}
    </ul>
  )
}

function show(feed: ModuleEntry[], code: Record<string, ModuleCode>) {
  const activate = vi.fn((m: ModuleEntry) => code[m.id])
  const modules: FrameModules = { feed, activate }
  const view = render(
    <SlotsProvider modules={modules}>
      <Owner />
    </SlotsProvider>,
  )
  return { ...view, activate, modules }
}
const hello: ComponentType<{ who: string }> = ({ who }) => <span>hello {who}</span>
const titles = () => screen.getAllByRole('listitem').map((li) => li.textContent?.split(':')[0])

describe('slots', () => {
  it("lists the owner's order first, the rest in feed order", async () => {
    show(
      [
        module('owner', { slots: [{ id: 'owner.tabs', order: ['c', 'a'] }] }),
        module('one', { into: [into('a'), into('b')] }),
        module('two', { into: [into('c'), into('d')] }),
      ],
      {},
    )
    expect(titles()).toEqual(['C', 'A', 'B', 'D'])
  })

  it("draws each contribution from its module's code, with the context the owner gives", async () => {
    const { activate } = show(
      [module('owner', { slots: [{ id: 'owner.tabs' }] }), module('one', { into: [into('a')] })],
      { one: { contributions: { a: hello } } },
    )
    expect(await screen.findByText('hello ada')).toBeInTheDocument()
    expect(activate).toHaveBeenCalledWith(expect.objectContaining({ id: 'one' }))
  })

  it("contains a contribution that throws: its place says so, and its neighbours stand", async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const boom = () => {
      throw new Error('broken on purpose')
    }
    show(
      [module('owner', { slots: [{ id: 'owner.tabs' }] }), module('bad', { into: [into('x')] }), module('good', { into: [into('y')] })],
      { bad: { contributions: { x: boom } }, good: { contributions: { y: hello } } },
    )
    expect(await screen.findByText('hello ada')).toBeInTheDocument()
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded: broken on purpose')
    vi.restoreAllMocks()
  })

  it('says so when the code offers no such contribution', async () => {
    show([module('owner', { slots: [{ id: 'owner.tabs' }] }), module('one', { into: [into('a')] })], { one: {} })
    expect(await screen.findByRole('alert')).toHaveTextContent('offers no contribution called a')
  })

  it('keeps one component per contribution across renders, so a contribution keeps its state', () => {
    const feed = [module('owner', { slots: [{ id: 'owner.tabs' }] }), module('one', { into: [into('a')] })]
    const modules: FrameModules = { feed, activate: () => ({ contributions: { a: hello } }) }
    const seen: unknown[] = []
    function Probe() {
      seen.push(useSlot('owner.tabs')[0]?.Component)
      return null
    }
    const view = render(
      <SlotsProvider modules={modules}>
        <Probe />
      </SlotsProvider>,
    )
    view.rerender(
      <SlotsProvider modules={modules}>
        <Probe />
      </SlotsProvider>,
    )
    expect(seen[0]).toBeDefined()
    expect(seen[1]).toBe(seen[0])
  })

  it('is empty outside a provider, and for a slot nobody fills', () => {
    render(<Owner />)
    expect(screen.queryAllByRole('listitem')).toEqual([])
  })
})
