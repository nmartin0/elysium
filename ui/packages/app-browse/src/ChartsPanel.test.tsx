import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

import type { VisibleSchema } from '@elysium/shell-api/types'

const aggregateObjects = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, aggregateObjects: (...args: unknown[]) => aggregateObjects(...args) }
})

// ECharts draws to a canvas jsdom cannot render. The wrapper has its
// own tests; here it is replaced by something a query can see, so
// these assert WHICH charts were built rather than how they look.
vi.mock('@elysium/shell-api/components/Chart', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div>{ariaLabel}</div>,
}))

const { default: ChartsPanel, chartableFields } = await import('./ChartsPanel')

const SCHEMA: VisibleSchema = {
  Customer: {
    fields: {
      region: { type: 'data', visibility: 'prominent', display_name: 'Region' },
      name: { type: 'data', visibility: 'normal' },
      internal: { type: 'data', visibility: 'hidden' },
      transactions: { type: 'link', target: 'Transaction' },
    },
  },
}

const noop = () => {}
const noop2 = () => {}

beforeEach(() => {
  vi.clearAllMocks()
  aggregateObjects.mockResolvedValue({ results: { 'us-west': 3, 'us-east': 1 } })
})

describe('which fields get a chart', () => {
  it('uses the fields the ontology declares prominent', () => {
    // The same metadata the result table defaults its columns to. An
    // author who said "these are what matter about a Customer" should
    // not have to say it twice.
    expect(chartableFields('Customer', SCHEMA).map((f) => f.field)).toEqual(['region'])
  })

  it('never charts a link field', () => {
    // Counting objects by a relationship has no meaning, and
    // /aggregate has no column to group on.
    const linkOnly: VisibleSchema = {
      Customer: { fields: { transactions: { type: 'link', target: 'Transaction' } } },
    }

    expect(chartableFields('Customer', linkOnly)).toEqual([])
  })

  it('falls back to every non-hidden field when none are prominent', () => {
    // A Charts tab showing NOTHING is worse than one showing too much.
    const plain: VisibleSchema = {
      Customer: {
        fields: {
          region: { type: 'data' },
          name: { type: 'data' },
          internal: { type: 'data', visibility: 'hidden' },
        },
      },
    }

    expect(chartableFields('Customer', plain).map((f) => f.field)).toEqual(['region', 'name'])
  })
})

describe('ChartsPanel', () => {
  it('asks for a count grouped by each chartable field', async () => {
    render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    await waitFor(() => expect(aggregateObjects).toHaveBeenCalledWith(
      'Customer',
      expect.objectContaining({ aggregate: 'count', group_by: 'region' }),
    ))
  })

  it('aggregates over the SAME object set the table is showing', async () => {
    // Charts describing a different set than the table beside them
    // would be actively misleading.
    const conditions = [{ field: 'region', operator: 'in', value: ['us-west'] }]
    render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={conditions}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    await waitFor(() => expect(aggregateObjects).toHaveBeenCalledWith(
      'Customer', expect.objectContaining({ conditions }),
    ))
  })

  it('draws a chart per field that has something to show', async () => {
    render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    expect(await screen.findByText('Region distribution')).toBeInTheDocument()
  })

  it('drops a field where every object shares one value', async () => {
    // One bar is not a distribution. Drawn, it would be a chart that
    // tells you nothing while looking like it should.
    aggregateObjects.mockResolvedValue({ results: { 'us-west': 4 } })

    render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    expect(await screen.findByText(/nothing to chart/)).toBeInTheDocument()
  })

  it('reports a failure rather than showing an empty tab', async () => {
    aggregateObjects.mockRejectedValue(new Error('aggregate unavailable'))

    render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    expect(await screen.findByText(/aggregate unavailable/)).toBeInTheDocument()
  })

  it('does not refetch when the parent re-renders with an equal filter', async () => {
    // The filter arrives as a new array on every parent render.
    // Depending on its identity would refetch every chart on every
    // keystroke in the search box beside it.
    const { rerender } = render(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )
    await waitFor(() => expect(aggregateObjects).toHaveBeenCalledTimes(1))

    rerender(
      <ChartsPanel objectType="Customer" visibleSchema={SCHEMA} conditions={[]}
                   filters={[]} onSelect={noop2} onSessionExpired={noop} />,
    )

    expect(aggregateObjects).toHaveBeenCalledTimes(1)
  })
})
