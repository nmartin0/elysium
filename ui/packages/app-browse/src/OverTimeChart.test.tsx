import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

import type { VisibleSchema } from '@elysium/shell-api/types'

import { answering } from './answering.testing'

const aggregateObjects = vi.fn()
const forecastObjects = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    aggregateObjects: (...args: unknown[]) => aggregateObjects(...args),
    forecastObjects: (...args: unknown[]) => forecastObjects(...args),
  }
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
const { forecastOption, overTimeOption, periodLabel } = await import('./aggregateCharts')

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
  aggregateObjects.mockImplementation(answering(WEEKS))
})

describe('a date field over time (R68)', () => {
  it('asks for a count per week of the same set the table lists', async () => {
    show([{ field: 'region', operator: 'equals', value: 'west' }])
    await screen.findByText(/records per week/)
    expect(aggregateObjects).toHaveBeenCalledWith('Order', {
      conditions: [{ field: 'region', operator: 'equals', value: 'west' }],
      q: 'refund',
      measures: [{ name: 'n', aggregate: 'count' }],
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
    aggregateObjects.mockImplementation(answering({ '2026-10-05': 4 }))
    show()
    expect(await screen.findByText(/all fall|falls in the same week/)).toBeInTheDocument()
  })

  it('says each period is a floor when the set was cut off', async () => {
    aggregateObjects.mockImplementation(answering(WEEKS, true))
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
    // ITS OWN POINT, hollow and NOT JOINED to the line: a line down to half
    // a week's count reads as a fall.
    expect(option.series[0]!.data).toEqual([2, 0, null])
    expect(option.series[1]).toMatchObject({
      name: 'So far',
      symbol: 'emptyCircle',
      showSymbol: true,
      showAllSymbol: true,
    })
    expect(option.series[1]!.data).toEqual([null, null, 1])
    const finished = overTimeOption(WEEKS, 'week', '2027-01-01') as { series: unknown[] }
    expect(finished.series).toHaveLength(1)
  })

  it('names periods at their own precision, in UTC', () => {
    expect(periodLabel('2026-10-01', 'month')).toMatch(/Oct 2026/)
    expect(periodLabel('2026-10-12', 'week')).toBe(`Week of ${periodLabel('2026-10-12', 'day')}`)
    // IN TIME ORDER whatever order the keys arrive in.
    const option = overTimeOption({ '2026-10-19': 1, '2026-10-05': 2, '2026-10-12': 0 }, 'week', '2027-01-01') as {
      series: { data: number[] }[]
    }
    expect(option.series[0]!.data).toEqual([2, 0, 1])
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
    aggregateObjects.mockImplementation((type: string, body: { period?: string; group_by?: string }) =>
      answering(body.period ? WEEKS : { west: 3, east: 1 })(type, body),
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

const FORECAST = {
  history: { '2026-09-28': 40, '2026-10-05': 50 },
  running: { start: '2026-10-12', value: 32 },
  points: [
    { start: '2026-10-12', value: 45, low: 40, high: 50 },
    { start: '2026-10-19', value: 46, low: 39, high: 53 },
  ],
  season: null,
  backtest: { form: 'a fading trend', origins: 4, horizon: 8, typical_miss: 2.6, naive_miss: 2.94, share: 0.07 },
  refusal: null,
}

describe('a forecast on the chart (R68)', () => {
  it('is asked for only when switched on, for the same set and period', async () => {
    forecastObjects.mockResolvedValue(FORECAST)
    show()
    await screen.findByText(/records per week:/)
    expect(forecastObjects).not.toHaveBeenCalled()
    fireEvent.click(screen.getByRole('checkbox', { name: 'Forecast' }))
    expect(await screen.findByText(/records per week, with a forecast/)).toBeInTheDocument()
    expect(forecastObjects).toHaveBeenCalledWith('Order', {
      conditions: [],
      q: 'refund',
      aggregate: 'count',
      group_by: 'placed',
      period: 'week',
    })
  })

  it('says how it was tested and against what', async () => {
    forecastObjects.mockResolvedValue(FORECAST)
    show()
    await screen.findByText(/records per week:/)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Forecast' }))
    expect(
      await screen.findByText(
        /Read as a fading trend\. Tested from 4 past points, 8 weeks ahead each time, it was off by about 2\.6 a week \(7% of a typical week\), against 2\.94 for simply carrying the last week on\./,
      ),
    ).toBeInTheDocument()
  })

  it('one that did not beat the naive forecast is not drawn, and says why', async () => {
    forecastObjects.mockResolvedValue({ ...FORECAST, points: [], refusal: 'it missed by as much as carrying on.' })
    show()
    await screen.findByText(/records per week:/)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Forecast' }))
    expect(await screen.findByText('No forecast: it missed by as much as carrying on.')).toBeInTheDocument()
    expect(screen.queryByText(/with a forecast/)).not.toBeInTheDocument()
  })

  it('dashed, anchored on the last finished period, with the band as its two edges', () => {
    const option = forecastOption(FORECAST, 'week') as {
      oneColour: boolean
      series: { name: string; data: unknown[]; lineStyle?: { type?: string } }[]
      tooltip: { formatter: (params: { dataIndex: number; axisValueLabel: string }[]) => string }
    }
    const byName = Object.fromEntries(option.series.map((series) => [series.name, series]))
    expect(option.oneColour).toBe(true)
    expect(byName['Recorded']!.data).toEqual([40, 50, null, null])
    expect(byName['So far']!.data).toEqual([null, null, 32, null])
    expect(byName['Forecast']!.data).toEqual([null, 50, 45, 46])
    expect(byName['Forecast']!.lineStyle?.type).toBe('dashed')
    expect(byName['80% range floor']!.data).toEqual([null, 50, 40, 39])
    expect(byName['80% range']!.data).toEqual([null, 0, 10, 14])
    const tip = option.tooltip.formatter([{ dataIndex: 2, axisValueLabel: 'Week of 12 Oct' }])
    expect(tip).toBe('Week of 12 Oct<br/>So far: 32<br/>Forecast: 45<br/>80% range: 40 to 50')
  })
})
