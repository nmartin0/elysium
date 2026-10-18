import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { VisibleSchema } from '@elysium/shell-api/types'

const aggregateObjects = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, aggregateObjects: (...args: unknown[]) => aggregateObjects(...args) }
})

// A canvas jsdom cannot read: the option is what is checked, so the
// stand-in prints the x-axis it was given.
vi.mock('@elysium/shell-api/components/Chart', () => ({
  default: ({ ariaLabel, option }: { ariaLabel: string; option: { xAxis?: { data?: string[] } } }) => (
    <div>
      {ariaLabel}: {(option.xAxis?.data ?? []).join(' | ')}
    </div>
  ),
}))

const { default: OverTimeChart } = await import('./OverTimeChart')
const { default: ChartsPanel } = await import('./ChartsPanel')
const { overTimeOption, periodLabel } = await import('./aggregateCharts')

const WEEKS = { '2026-10-05': 2, '2026-10-12': 0, '2026-10-19': 1 }

function show(conditions: unknown[] = []) {
  render(
    <OverTimeChart
      objectType="Order"
      field="placed"
      label="Placed"
      conditions={conditions}
      queryText="refund"
      onSessionExpired={() => {}}
    />,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  aggregateObjects.mockResolvedValue({ results: WEEKS })
})

describe('a date field over time (R68)', () => {
  it('asks for a count per week of the same set the table lists', async () => {
    show([{ field: 'region', operator: 'equals', value: 'west' }])
    await screen.findByText(/records per week/)
    expect(aggregateObjects).toHaveBeenCalledWith('Order', {
      conditions: [{ field: 'region', operator: 'equals', value: 'west' }],
      q: 'refund',
      aggregate: 'count',
      group_by: 'placed',
      period: 'week',
    })
  })

  it('draws the periods in order, the empty week included', async () => {
    show()
    // In the reader's own locale and against today's date, so built the
    // same way here.
    const option = overTimeOption(WEEKS, 'week') as { xAxis: { data: string[] } }
    const axis = option.xAxis.data.join(' | ')
    expect(await screen.findByText(`Placed: records per week: ${axis}`)).toBeInTheDocument()
    expect(axis).toMatch(/^Week of .*5.*\| Week of .*12.*\| Week of .*19/)
  })

  it('counts by day or month when asked', async () => {
    show()
    await screen.findByText(/records per week/)
    fireEvent.click(screen.getByRole('button', { name: 'Month' }))
    await waitFor(() =>
      expect(aggregateObjects).toHaveBeenLastCalledWith('Order', expect.objectContaining({ period: 'month' })),
    )
    expect(screen.getByRole('button', { name: 'Month' })).toHaveAttribute('aria-pressed', 'true')
  })

  it('one period is not a line, and says so', async () => {
    aggregateObjects.mockResolvedValue({ results: { '2026-10-05': 4 } })
    show()
    expect(await screen.findByText(/all fall|falls in the same week/)).toBeInTheDocument()
  })

  it('says each period is a floor when the set was cut off', async () => {
    aggregateObjects.mockResolvedValue({ results: WEEKS, scan_truncated: true })
    show()
    expect(await screen.findByText(/each week is at least what it says/)).toBeInTheDocument()
  })

  it('marks the period still running as so far, so its drop is not read as a fall', async () => {
    const { unfinished } = await import('./aggregateCharts')
    expect(unfinished('2026-10-12', 'week', '2026-10-14')).toBe(true)
    expect(unfinished('2026-10-12', 'week', '2026-10-19')).toBe(false)
    expect(unfinished('2026-10-01', 'month', '2026-10-31')).toBe(true)
    const option = overTimeOption(WEEKS, 'week', '2026-10-21') as {
      xAxis: { data: string[] }
      series: { data: unknown[] }[]
    }
    expect(option.xAxis.data.at(-1)).toMatch(/\(so far\)$/)
    expect(option.xAxis.data.slice(0, -1).some((label) => label.includes('so far'))).toBe(false)
    expect(option.series[0]!.data.at(-1)).toMatchObject({ value: 1, symbol: 'emptyCircle' })
    // THE ONE POINT ALWAYS DRAWN: on a long line the finished ones are not.
    const long = Object.fromEntries(
      Array.from({ length: 30 }, (_, index) => [
        new Date(Date.UTC(2026, 0, 5 + 7 * index)).toISOString().slice(0, 10),
        index,
      ]),
    )
    const sizes = (
      overTimeOption(long, 'week', '2026-07-29') as { series: { data: { symbolSize: number }[] }[] }
    ).series[0]!.data.map((point) => point.symbolSize)
    expect(sizes.at(-1)).toBeGreaterThan(0)
    expect(sizes.slice(0, -1).every((size) => size === 0)).toBe(true)
  })

  it('names periods at their own precision, in UTC', () => {
    expect(periodLabel('2026-10-01', 'month')).toMatch(/Oct 2026/)
    expect(periodLabel('2026-10-12', 'week')).toBe(`Week of ${periodLabel('2026-10-12', 'day')}`)
    // IN TIME ORDER whatever order the keys arrive in.
    const option = overTimeOption({ '2026-10-19': 1, '2026-10-05': 2, '2026-10-12': 0 }, 'week', '2027-01-01') as {
      series: { data: { value: number }[] }[]
    }
    expect(option.series[0]!.data.map((point) => point.value)).toEqual([2, 0, 1])
  })
})

describe('in the charts panel', () => {
  it('a date field is drawn over time, not counted value by value', async () => {
    const schema: VisibleSchema = {
      Order: {
        fields: {
          placed: { type: 'data', visibility: 'prominent', display_name: 'Placed', data_type: 'date' },
          region: { type: 'data', visibility: 'prominent', display_name: 'Region' },
        },
      },
    }
    aggregateObjects.mockImplementation((_type: string, body: { period?: string }) =>
      Promise.resolve({ results: body.period ? WEEKS : { west: 3, east: 1 } }),
    )
    render(
      <ChartsPanel
        objectType="Order"
        visibleSchema={schema}
        queryText=""
        filters={[]}
        onSelect={() => {}}
        onSessionExpired={() => {}}
      />,
    )
    expect(await screen.findByText(/Placed: records per week/)).toBeInTheDocument()
    expect(await screen.findByText(/Region distribution/)).toBeInTheDocument()
    const grouped = aggregateObjects.mock.calls.map(([, body]) => [body.group_by, body.period])
    expect(grouped).toEqual(
      expect.arrayContaining([
        ['placed', 'week'],
        ['region', undefined],
      ]),
    )
    expect(grouped).not.toContainEqual(['placed', undefined])
  })
})
