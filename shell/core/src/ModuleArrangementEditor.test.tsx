import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ArrangedModule, ModuleArrangement, ModuleArrangementChange } from './contract'
import { ModuleArrangementEditor, type ModuleManager } from './ModuleArrangementEditor'

const row = (id: string, extra: Partial<ArrangedModule> = {}): ArrangedModule => ({
  id,
  name: id.toUpperCase(),
  version: '1',
  enabled: true,
  pinned: false,
  pages: [`/${id}`],
  ...extra,
})
const ARRANGEMENT: ModuleArrangement = {
  home: '/a',
  modules: [row('a'), row('b', { pages: ['/b', '/b/:id'] }), row('c', { enabled: false }), row('sys', { pinned: true })],
  digest: 'd1',
}

function manager(overrides: Partial<ModuleManager> = {}): ModuleManager {
  return {
    read: vi.fn(async () => ARRANGEMENT),
    save: vi.fn(async (change: ModuleArrangementChange) => ({
      home: change.home,
      modules: [...change.modules.map(([id, enabled]) => row(id, { enabled })), row('sys', { pinned: true })],
      digest: 'd2',
    })),
    refresh: vi.fn(async () => {}),
    ...overrides,
  }
}

async function shown(m: ModuleManager) {
  render(<ModuleArrangementEditor manager={m} />)
  await screen.findByRole('heading', { name: 'Arrangement, for everyone' })
}
const order = () =>
  within(screen.getByRole('list'))
    .getAllByRole('listitem')
    .map((li) => li.querySelector('label')!.textContent)
const save = () => screen.getByRole('button', { name: 'Save' })

describe('the module manager', () => {
  it('shows every module in rail order, pinned last and not switchable', async () => {
    await shown(manager())
    expect(order()).toEqual(['A', 'B', 'C', 'SYS'])
    expect(screen.getByRole('checkbox', { name: 'C' })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: 'SYS' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Move SYS up' })).not.toBeInTheDocument()
  })

  it('changes nothing until Save, and Discard puts the draft back', async () => {
    const m = manager()
    await shown(m)
    expect(save()).toBeDisabled()

    fireEvent.click(screen.getByRole('checkbox', { name: 'B' }))
    fireEvent.click(screen.getByRole('button', { name: 'Move C up' }))
    expect(order()).toEqual(['A', 'C', 'B', 'SYS'])
    expect(m.save).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: 'Discard' }))
    expect(order()).toEqual(['A', 'B', 'C', 'SYS'])
    expect(screen.getByRole('checkbox', { name: 'B' })).toBeChecked()
    expect(save()).toBeDisabled()
  })

  it('saves every arrangeable module in order, against the digest it read, then refreshes the feed', async () => {
    const m = manager()
    await shown(m)
    fireEvent.click(screen.getByRole('checkbox', { name: 'C' }))
    fireEvent.click(screen.getByRole('button', { name: 'Move C up' }))

    await act(async () => fireEvent.click(save()))

    expect(m.save).toHaveBeenCalledWith({
      home: '/a',
      modules: [
        ['a', true],
        ['c', true],
        ['b', true],
      ],
      digest: 'd1',
    })
    expect(m.refresh).toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Saved.')
    expect(save()).toBeDisabled()
  })

  it('offers as home only static pages of modules that are on', async () => {
    await shown(manager())
    const choices = within(screen.getByRole('combobox')).getAllByRole('option').map((o) => o.textContent)
    expect(choices).toEqual(['/a', '/b', '/sys'])
  })

  it('says why a save was refused, and keeps the draft', async () => {
    const m = manager({ save: vi.fn(async () => Promise.reject(new Error('The modules changed since you opened them.'))) })
    await shown(m)
    fireEvent.click(screen.getByRole('checkbox', { name: 'B' }))

    await act(async () => fireEvent.click(save()))

    expect(screen.getByRole('alert')).toHaveTextContent('Not saved: The modules changed since you opened them.')
    expect(screen.getByRole('checkbox', { name: 'B' })).not.toBeChecked()
    expect(m.refresh).not.toHaveBeenCalled()
  })

  it('says so when the arrangement cannot be read', async () => {
    render(<ModuleArrangementEditor manager={manager({ read: vi.fn(async () => Promise.reject(new Error('403'))) })} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('The arrangement could not be read: 403')
  })

  it('refreshes on request, for a bundle rebuilt since the page loaded', async () => {
    const m = manager()
    await shown(m)
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Refresh modules' })))
    expect(m.refresh).toHaveBeenCalled()
    expect(screen.getByRole('status')).toHaveTextContent('Refreshed.')
  })
})
