import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { VisibleSchema } from '@elysium/shell-api/types'

/** Counts and freshness (DEV_UI 14.5), per test; by default never
 *  settled, so the tests not about them see the nodes as before. Plain
 *  functions, not vi.fn: see WhoCanSee.test.tsx on rejections. */
let counts: () => Promise<unknown> = () => new Promise(() => {})
let freshness: () => Promise<unknown> = () => new Promise(() => {})
vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyCanvas: vi.fn(),
  saveOntologyCanvas: vi.fn(),
  saveSharedOntologyCanvas: vi.fn(),
  clearSharedOntologyCanvas: vi.fn(),
  getVisibleActionTypesCached: vi.fn(),
  getTypeCounts: () => counts(),
  getDataFreshness: () => freshness(),
}))

import {
  clearSharedOntologyCanvas,
  getOntologyCanvas,
  getVisibleActionTypesCached,
  saveOntologyCanvas,
  saveSharedOntologyCanvas,
} from '@elysium/shell-api/api'
import OntologyCanvas from './OntologyCanvas'

const mockedGet = vi.mocked(getOntologyCanvas)
const mockedSave = vi.mocked(saveOntologyCanvas)
const mockedShare = vi.mocked(saveSharedOntologyCanvas)
const mockedUnshare = vi.mocked(clearSharedOntologyCanvas)
const mockedActions = vi.mocked(getVisibleActionTypesCached)

/**
 * WHAT jsdom CAN AND CANNOT SAY HERE. Positions are computed by us, not
 * by the browser, so a node's transform is a number this file can read
 * -- that is the point of computing them. What it cannot see is whether
 * the drawing LOOKS right: overlaps, legibility, the cascade. Those were
 * checked in a browser and the canvas has an e2e test.
 */
const SCHEMA: VisibleSchema = {
  Customer: {
    group: 'Accounts',
    fields: {
      region: { type: 'data' },
      transactions: { type: 'link', target: 'Transaction', link_type: 'cust_tx', cardinality: 'one_to_many' },
    },
  },
  Transaction: {
    fields: {
      amount: { type: 'data' },
      customer: { type: 'link', target: 'Customer', link_type: 'cust_tx', cardinality: 'many_to_one' },
    },
  },
  Ticket: { fields: { subject: { type: 'data' } } },
}

function node(name: string) {
  // An SVG <g>, typed as an element testing-library will query inside.
  return document.querySelector(`[data-type="${name}"]`) as unknown as HTMLElement
}

function translateOf(name: string) {
  const match = /translate\(([-\d.e]+) ([-\d.e]+)\)/.exec(node(name).getAttribute('transform') ?? '')
  return { x: Number(match![1]), y: Number(match![2]) }
}

function renderCanvas(props: Partial<React.ComponentProps<typeof OntologyCanvas>> = {}) {
  const onSelect = vi.fn()
  render(<OntologyCanvas schema={SCHEMA} selection={null} onSelect={onSelect} {...props} />)
  return { onSelect }
}

beforeEach(() => {
  vi.clearAllMocks()
  counts = () => new Promise(() => {})
  freshness = () => new Promise(() => {})
  mockedGet.mockResolvedValue({ positions: {}, areas: [] })
  mockedSave.mockImplementation(async (layout) => ({ ...layout }))
  mockedActions.mockResolvedValue({
    Refund: { affected_object_types: ['Transaction'] },
    Escalate: { affected_object_types: ['Transaction'] },
  })
})

describe('the ontology canvas (DEV_UI 14)', () => {
  it('draws a type per visible type, with its counts', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Transaction')).toBeTruthy())
    expect(node('Customer').getAttribute('aria-label')).toBe('Customer: 1 field, 1 link, read-only')
    await waitFor(() =>
      expect(node('Transaction').getAttribute('aria-label')).toBe('Transaction: 1 field, 1 link, 2 actions'),
    )
  })

  it('puts actions ON the type, not as nodes (14.3)', async () => {
    renderCanvas()
    await waitFor(() => expect(within(node('Transaction')).getByText('2 actions')).toBeInTheDocument())
    expect(document.querySelector('[data-type="Refund"]')).toBeNull()
  })

  it('draws a two-sided link once, with its cardinality', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    expect(document.querySelectorAll('[data-edge="cust_tx"]')).toHaveLength(1)
  })

  it('draws every link label after every line, so no line can cross one', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    const everything = [...document.querySelectorAll('.ontology-canvas__line, .ontology-canvas__edge-label')]
    const lastLine = everything.map((el) => el.classList.contains('ontology-canvas__line')).lastIndexOf(true)
    const firstLabel = everything.findIndex((el) => el.classList.contains('ontology-canvas__edge-label'))
    expect(firstLabel).toBeGreaterThan(lastLine)
    expect(document.querySelectorAll('.ontology-canvas__edge-label').length).toBeGreaterThan(0)
  })

  it('selecting a type is a click, or Enter on its focus -- the keyboard reaches everything', async () => {
    const { onSelect } = renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())

    fireEvent.click(node('Customer'))
    expect(onSelect).toHaveBeenLastCalledWith({ kind: 'object', name: 'Customer' })

    fireEvent.keyDown(node('Ticket'), { key: 'Enter' })
    expect(onSelect).toHaveBeenLastCalledWith({ kind: 'object', name: 'Ticket' })
  })

  it('selecting an edge opens the link', async () => {
    const { onSelect } = renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    fireEvent.click(document.querySelector('[data-edge="cust_tx"] .ontology-canvas__hit')!)
    expect(onSelect).toHaveBeenCalledWith(expect.objectContaining({ kind: 'link', name: 'cust_tx' }))
  })
})

describe('a moved type stays where it was put (14.1)', () => {
  it('honours a saved position', async () => {
    mockedGet.mockResolvedValue({ positions: { Ticket: { x: 1000, y: 2000 } }, areas: [] })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 188 / 2))
  })

  it('an arrow key moves it, and the move is saved once the keys stop', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    const before = translateOf('Ticket')

    fireEvent.keyDown(node('Ticket'), { key: 'ArrowRight' })
    fireEvent.keyDown(node('Ticket'), { key: 'ArrowRight', shiftKey: true })

    expect(translateOf('Ticket').x).toBe(before.x + 16 + 64)
    expect(mockedSave).not.toHaveBeenCalled()
    await waitFor(() => expect(mockedSave).toHaveBeenCalledTimes(1), { timeout: 2000 })
    const saved = mockedSave.mock.calls[0]![0]
    expect(Object.keys(saved.positions)).toEqual(['Ticket'])
  })

  it('auto-layout forgets the moves and can be undone, rather than asking first', async () => {
    mockedGet.mockResolvedValue({ positions: { Ticket: { x: 1000, y: 2000 } }, areas: [] })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 94))

    fireEvent.click(screen.getByRole('button', { name: 'Auto-layout' }))
    await waitFor(() => expect(mockedSave).toHaveBeenLastCalledWith({ positions: {}, areas: [] }))
    expect(translateOf('Ticket').x).not.toBe(1000 - 94)

    fireEvent.click(screen.getByRole('button', { name: 'Undo auto-layout' }))
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 94))
    expect(mockedSave).toHaveBeenLastCalledWith({ positions: { Ticket: { x: 1000, y: 2000 } }, areas: [] })
  })

  it('says so when a save fails, rather than pretending', async () => {
    mockedSave.mockRejectedValue(new Error('disk full'))
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    fireEvent.keyDown(node('Ticket'), { key: 'ArrowDown' })
    expect(await screen.findByText(/Not saved: disk full/, {}, { timeout: 2000 })).toBeInTheDocument()
  })
})

describe('subject areas (14.4)', () => {
  it("offers the ontology's own groups, and choosing one dims everything else", async () => {
    renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    const areas = screen.getByRole('navigation', { name: 'Subject areas' })
    expect(within(areas).getByText('from the ontology')).toBeInTheDocument()

    fireEvent.click(within(areas).getByRole('button', { name: /Accounts/ }))

    expect(node('Customer').classList.contains('ontology-canvas__node--dimmed')).toBe(false)
    expect(node('Ticket').classList.contains('ontology-canvas__node--dimmed')).toBe(true)
  })

  it('makes one of their own from the type they have selected, and saves it', async () => {
    renderCanvas({ selection: { kind: 'object', name: 'Ticket' } })
    await waitFor(() => expect(node('Ticket')).toBeTruthy())

    fireEvent.click(screen.getByRole('button', { name: 'New subject area' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('checkbox', { name: 'Ticket' })).toBeChecked()
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'Support' } })
    fireEvent.click(within(dialog).getByRole('checkbox', { name: 'Customer' }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockedSave).toHaveBeenLastCalledWith({
        positions: {},
        areas: [{ name: 'Support', types: ['Customer', 'Ticket'] }],
      }),
    )
  })

  it('refuses a second area of the same name before it reaches the server', async () => {
    mockedGet.mockResolvedValue({ positions: {}, areas: [{ name: 'Support', types: [] }] })
    renderCanvas()
    await screen.findByRole('button', { name: /^Support/ })

    fireEvent.click(screen.getByRole('button', { name: 'New subject area' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.change(within(dialog).getByLabelText('Name'), { target: { value: 'support' } })
    expect(within(dialog).getByText(/already have a subject area called support/)).toBeInTheDocument()
    expect(within(dialog).getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})

describe('the security layer (14.5)', () => {
  it('is not offered to someone who may not see the permission model', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    expect(screen.queryByRole('checkbox', { name: 'Security chains' })).toBeNull()
  })

  it('draws a borrowed chain on its own layer, when switched on', async () => {
    mockedGet.mockResolvedValue({
      positions: {},
      areas: [],
      security_chains: [
        { type: 'Customer', kind: 'field', field: 'region' },
        { type: 'Transaction', kind: 'via', field: 'customer', target: 'Customer' },
      ],
    })
    renderCanvas()
    const toggle = await screen.findByRole('checkbox', { name: 'Security chains' })
    expect(node('Transaction').getAttribute('aria-label')).toContain('secured via Customer')
    expect(document.querySelector('.ontology-canvas__edge--security')).toBeNull()

    fireEvent.click(toggle)
    const chain = document.querySelector('.ontology-canvas__edge--security')!
    expect(chain.querySelector('title')!.textContent).toBe(
      'Transaction borrows its security from Customer, through customer',
    )
    expect(chain.querySelector('text')).toBeNull()
  })
})

describe('counts, health and close zoom (DEV_UI 14.5)', () => {
  it('puts how many the reader can see, and whether it is current, on each node', async () => {
    counts = () =>
      Promise.resolve({
        Customer: { count: 1284, scan_truncated: false },
        Transaction: { count: 10000, scan_truncated: true },
      })
    freshness = () =>
      Promise.resolve({
        source: 'gold',
        last_synced_at: null,
        freshness: { Customer: { state: 'fail' }, Transaction: { state: 'fresh' }, Ticket: { state: 'exempt' } },
      })
    renderCanvas()

    await waitFor(() => expect(within(node('Customer')).getByText('1,284')).toBeTruthy())
    expect(within(node('Transaction')).getByText('10,000+')).toBeTruthy()
    expect(node('Customer').getAttribute('aria-label')).toMatch(/1,284 you can see, data overdue$/)
    expect(node('Customer').querySelector('.ontology-canvas__health--fail')).not.toBeNull()
    expect(node('Transaction').querySelector('.ontology-canvas__health--fresh')).not.toBeNull()
    // EXEMPT IS UNJUDGED: no dot at all, rather than a reassuring one.
    expect(node('Ticket').querySelector('.ontology-canvas__health')).toBeNull()
  })

  it('draws nothing extra when counts and freshness are refused', async () => {
    counts = () => Promise.reject(new Error('no'))
    freshness = () => Promise.reject(new Error('no'))
    renderCanvas()

    await waitFor(() => expect(node('Customer')).toBeTruthy())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(node('Customer').querySelector('.ontology-canvas__count, .ontology-canvas__health')).toBeNull()
  })

  it('lists the fields once zoomed in close, and summarises them before', async () => {
    renderCanvas({ schema: { ...SCHEMA, Customer: { ...SCHEMA.Customer, id_field: 'customer_id' } } })
    await waitFor(() => expect(node('Customer')).toBeTruthy())
    expect(node('Customer').querySelector('.ontology-canvas__field')).toBeNull()

    for (let i = 0; i < 4; i++) fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }))

    const fields = [...node('Customer').querySelectorAll('.ontology-canvas__field')].map((f) => f.textContent)
    // THE KEY FIRST, even though it is not a declared field.
    expect(fields).toEqual(['customer_id', 'region'])
    expect(node('Customer').querySelector('.ontology-canvas__field--key')?.textContent).toBe('customer_id')
  })
})

describe('the arrangement everyone starts from', () => {
  it('starts from the shared arrangement when the person has moved nothing', async () => {
    mockedGet.mockResolvedValue({ positions: {}, areas: [], shared_positions: { Ticket: { x: 1000, y: 2000 } } })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 94))
  })

  it('lets a personal move win over the shared one', async () => {
    mockedGet.mockResolvedValue({
      positions: { Ticket: { x: 300, y: 400 } },
      areas: [],
      shared_positions: { Ticket: { x: 1000, y: 2000 } },
    })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(300 - 94))
  })

  it('falls back to the shared arrangement, not the automatic one, on auto-layout', async () => {
    mockedGet.mockResolvedValue({
      positions: { Ticket: { x: 300, y: 400 } },
      areas: [],
      shared_positions: { Ticket: { x: 1000, y: 2000 } },
    })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(300 - 94))
    fireEvent.click(screen.getByRole('button', { name: 'Auto-layout' }))
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 94))
  })

  it('offers the buttons only to someone who may set it', async () => {
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'Start everyone here' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear shared start' })).not.toBeInTheDocument()
  })

  it('asks before changing where everyone starts, then sends every placed type', async () => {
    mockedGet.mockResolvedValue({ positions: {}, areas: [], can_set_shared: true })
    mockedShare.mockImplementation(async (positions) => ({
      positions: {},
      areas: [],
      shared_positions: positions,
      can_set_shared: true,
    }))
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    expect(screen.queryByRole('button', { name: 'Clear shared start' })).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Start everyone here' }))
    expect(mockedShare).not.toHaveBeenCalled()
    const confirm = await screen.findByRole('button', { name: 'Use this arrangement' })
    expect(confirm).toHaveClass('bp6-intent-primary')
    fireEvent.click(confirm)

    await waitFor(() => expect(mockedShare).toHaveBeenCalledTimes(1))
    expect(Object.keys(mockedShare.mock.calls[0]![0]).sort()).toEqual(['Customer', 'Ticket', 'Transaction'])
    expect(await screen.findByText('Everyone now starts from this arrangement')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Clear shared start' })).toBeInTheDocument()
  })

  it('does nothing when the confirmation is cancelled', async () => {
    mockedGet.mockResolvedValue({ positions: {}, areas: [], can_set_shared: true })
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Start everyone here' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(mockedShare).not.toHaveBeenCalled()
  })

  it('clears the shared start after asking, and the button goes', async () => {
    mockedGet.mockResolvedValue({
      positions: {},
      areas: [],
      can_set_shared: true,
      shared_positions: { Ticket: { x: 1000, y: 2000 } },
    })
    mockedUnshare.mockResolvedValue({ positions: {}, areas: [], shared_positions: {}, can_set_shared: true })
    renderCanvas()
    await waitFor(() => expect(translateOf('Ticket').x).toBe(1000 - 94))

    fireEvent.click(screen.getByRole('button', { name: 'Clear shared start' }))
    expect(mockedUnshare).not.toHaveBeenCalled()
    fireEvent.click(await screen.findByRole('button', { name: 'Clear it' }))

    await waitFor(() => expect(mockedUnshare).toHaveBeenCalledTimes(1))
    expect(await screen.findByText('Everyone now starts from the automatic layout')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Clear shared start' })).not.toBeInTheDocument()
    expect(translateOf('Ticket').x).not.toBe(1000 - 94)
  })

  it('says so when setting it fails', async () => {
    mockedGet.mockResolvedValue({ positions: {}, areas: [], can_set_shared: true })
    mockedShare.mockRejectedValue(new Error('not allowed'))
    renderCanvas()
    await waitFor(() => expect(node('Ticket')).toBeTruthy())
    fireEvent.click(screen.getByRole('button', { name: 'Start everyone here' }))
    fireEvent.click(await screen.findByRole('button', { name: 'Use this arrangement' }))
    expect(await screen.findByText(/Not saved: not allowed/)).toBeInTheDocument()
  })
})
