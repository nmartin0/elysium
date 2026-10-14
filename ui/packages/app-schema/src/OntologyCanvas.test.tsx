import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import type { VisibleSchema } from '@elysium/shell-api/types'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getOntologyCanvas: vi.fn(),
  saveOntologyCanvas: vi.fn(),
  getVisibleActionTypesCached: vi.fn(),
}))

import { getOntologyCanvas, getVisibleActionTypesCached, saveOntologyCanvas } from '@elysium/shell-api/api'
import OntologyCanvas from './OntologyCanvas'

const mockedGet = vi.mocked(getOntologyCanvas)
const mockedSave = vi.mocked(saveOntologyCanvas)
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
