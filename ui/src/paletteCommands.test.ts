import { describe, expect, it, vi } from 'vitest'
import {
  MAX_SEARCH_SUGGESTIONS,
  actionCommands,
  objectInScope,
  searchSuggestions,
  typeCommands,
  viewCommands,
} from './paletteCommands'

const SCHEMA = { Customer: { fields: {} }, Account: { fields: {} }, Transaction: { fields: {} } }

describe('the palette beyond "go to" (DEV_UI 10.1)', () => {
  it('offers each type the reader may see, as a link into Browse', () => {
    const go = vi.fn()
    const commands = typeCommands(SCHEMA, go)
    expect(commands.map((c) => c.label)).toEqual(['Browse Account', 'Browse Customer', 'Browse Transaction'])
    commands[1]!.run()
    expect(go).toHaveBeenCalledWith('/browse?type=Customer')
  })

  it('opens a saved view by its id, which Browse resolves', () => {
    const go = vi.fn()
    const [command] = viewCommands([{ view_id: 'v 1', name: 'Big refunds', object_type: 'Transaction' }], go)
    expect(command!.label).toBe('Big refunds')
    expect(command!.group).toContain('Transaction')
    command!.run()
    expect(go).toHaveBeenCalledWith('/browse?saved=v%201')
  })

  it('knows which object a page is about', () => {
    expect(objectInScope('/objects/Customer/cust%20001')).toEqual({ type: 'Customer', id: 'cust 001' })
    expect(objectInScope('/browse')).toBeNull()
    expect(objectInScope('/objects/Customer')).toBeNull()
  })

  describe('actions, scoped to the object on screen', () => {
    const ACTIONS = {
      Escalate: { affected_object_types: ['Customer'], executable: true },
      Close: { affected_object_types: ['Customer'], executable: false },
      Transfer: { affected_object_types: ['Account'], executable: true },
    }

    it('offers only actions on this type, each opening its form here', () => {
      const go = vi.fn()
      const commands = actionCommands({ type: 'Customer', id: 'c1' }, ACTIONS, go)
      expect(commands.map((c) => c.label)).toEqual(['Close', 'Escalate'])
      commands[1]!.run()
      expect(go).toHaveBeenCalledWith('/objects/Customer/c1?action=Escalate')
    })

    it('lists one the reader may not run, greyed WITH THE REASON', () => {
      const close = actionCommands({ type: 'Customer', id: 'c1' }, ACTIONS, vi.fn()).find((c) => c.label === 'Close')
      expect(close!.unavailable).toMatch(/not run it/)
    })

    it('offers none off an object page', () => {
      expect(actionCommands(null, ACTIONS, vi.fn())).toEqual([])
    })
  })

  describe('suggested searches', () => {
    it('nothing typed, nothing suggested', () => {
      expect(searchSuggestions('  ', SCHEMA, null, vi.fn())).toEqual([])
    })

    it('the type being browsed first, then the rest', () => {
      const go = vi.fn()
      const commands = searchSuggestions('ada', SCHEMA, 'Transaction', go)
      expect(commands.map((c) => c.label)).toEqual([
        'Search Transaction for “ada”',
        'Search Account for “ada”',
        'Search Customer for “ada”',
      ])
      commands[0]!.run()
      expect(go).toHaveBeenCalledWith('/browse?type=Transaction&q=ada')
    })

    it('in at most a handful of types', () => {
      const many = Object.fromEntries(Array.from({ length: 12 }, (_, i) => [`Type${i}`, { fields: {} }]))
      expect(searchSuggestions('x', many, null, vi.fn())).toHaveLength(MAX_SEARCH_SUGGESTIONS)
    })
  })
})
