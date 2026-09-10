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
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    await waitFor(() =>
      expect(aggregateObjects).toHaveBeenCalledWith(
        'Customer',
        expect.objectContaining({ aggregate: 'count', group_by: 'region' }),
      ),
    )
  })

  it('excludes a field\u2019s OWN selection from its own chart', async () => {
    // A chart that filtered itself dropped to one bar the moment you
    // clicked it -- and the panel then discarded it as having nothing
    // to show, so every chart vanished on the first click. Found by
    // using it.
    const filters = [{ field: 'region', values: ['us-west'], mode: 'keep' as const }]
    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={filters}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    await waitFor(() =>
      expect(aggregateObjects).toHaveBeenCalledWith('Customer', expect.objectContaining({ conditions: [] })),
    )
  })

  it('draws a chart per field that has something to show', async () => {
    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    expect(await screen.findByText('Region distribution')).toBeInTheDocument()
  })

  it('drops a field where every object shares one value', async () => {
    // One bar is not a distribution. Drawn, it would be a chart that
    // tells you nothing while looking like it should.
    aggregateObjects.mockResolvedValue({ results: { 'us-west': 4 } })

    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    expect(await screen.findByText(/nothing to chart/)).toBeInTheDocument()
  })

  it('reports a failure rather than showing an empty tab', async () => {
    aggregateObjects.mockRejectedValue(new Error('aggregate unavailable'))

    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    expect(await screen.findByText(/aggregate unavailable/)).toBeInTheDocument()
  })

  it('does not refetch when the parent re-renders with an equal filter', async () => {
    // The filter arrives as a new array on every parent render.
    // Depending on its identity would refetch every chart on every
    // keystroke in the search box beside it.
    const { rerender } = render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )
    await waitFor(() => expect(aggregateObjects).toHaveBeenCalledTimes(1))

    rerender(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    expect(aggregateObjects).toHaveBeenCalledTimes(1)
  })
})

describe('a chart does not filter itself', () => {
  it('keeps a chart on screen after its own bar is clicked', async () => {
    /**
     * THE bug this file's tests missed, found by using it.
     *
     * Clicking "us-west" on the region chart filtered the region chart
     * to us-west, leaving it a single value. The panel then dropped it
     * as having nothing to show, so every chart vanished on the first
     * click and the tab read "nothing to chart".
     *
     * The existing tests passed an already-narrowed `conditions` prop
     * and never exercised the loop where a selection becomes the
     * filter for the chart that produced it.
     */
    aggregateObjects.mockImplementation((_type: string, body: { conditions?: unknown[] }) => {
      // A stand-in for the server: applying a region filter really does
      // leave one region.
      const filtered = (body.conditions ?? []).length > 0
      return Promise.resolve({
        results: filtered ? { 'us-west': 3 } : { 'us-west': 3, 'us-east': 1 },
      })
    })

    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={SCHEMA}
        queryText=""
        filters={[{ field: 'region', values: ['us-west'], mode: 'keep' }]}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    expect(await screen.findByText('Region distribution')).toBeInTheDocument()
  })

  it('still applies OTHER charts\u2019 selections to a chart', async () => {
    // Excluding a field's own selection must not mean excluding
    // everything -- cross-filtering is the point.
    const filters = [
      { field: 'region', values: ['us-west'], mode: 'keep' as const },
      { field: 'name', values: ['Ada'], mode: 'keep' as const },
    ]

    render(
      <ChartsPanel
        objectType="Customer"
        visibleSchema={{
          Customer: {
            fields: {
              region: { type: 'data', visibility: 'prominent', display_name: 'Region' },
              name: { type: 'data', visibility: 'prominent', display_name: 'Name' },
            },
          },
        }}
        queryText=""
        filters={filters}
        onSelect={noop2}
        onSessionExpired={noop}
      />,
    )

    // The region chart sees the NAME filter but not its own.
    await waitFor(() =>
      expect(aggregateObjects).toHaveBeenCalledWith(
        'Customer',
        expect.objectContaining({
          group_by: 'region',
          conditions: [{ field: 'name', operator: 'in', value: ['Ada'] }],
        }),
      ),
    )
  })
})
