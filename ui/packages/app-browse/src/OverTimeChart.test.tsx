import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
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

// A canvas jsdom cannot read. The time chart's stand-in prints the lines
// it was given, a hollow (unfinished) point starred; the others print
// their name.
vi.mock('@elysium/shell-api/components/TimeChart', () => ({
  default: ({
    ariaLabel,
    series,
    grain,
  }: {
    ariaLabel: string
    series: { name: string; dashed?: boolean; points: { at: string; value: number | null; partial?: boolean }[] }[]
    grain?: string
  }) => (
    <div>
      {ariaLabel} ({grain}):{' '}
      {series
        .map(
          (line) =>
            `${line.name}${line.dashed ? ' dashed' : ''}[${line.points.map((p) => `${p.at}=${p.value}${p.partial ? '*' : ''}`).join(' ')}]`,
        )
        .join(' ')}
    </div>
  ),
}))
vi.mock('@elysium/shell-api/components/Chart', () => ({
  default: ({ ariaLabel }: { ariaLabel: string }) => <div>{ariaLabel}</div>,
}))

const { default: OverTimeChart } = await import('./OverTimeChart')
const { default: ChartsPanel } = await import('./ChartsPanel')
const { countSeries, forecastSeries, unfinished } = await import('./aggregateCharts')
const { timeChartOption } = await import('@elysium/shell-api/timeChart')

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
  // A DATE THAT IS NOT TODAY'S: which period is still running depends on
  // it, and a test that read the real date would pass on some days.
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(new Date('2027-01-01T12:00:00Z'))
  vi.clearAllMocks()
  aggregateObjects.mockImplementation(answering(WEEKS))
})

afterEach(() => {
  vi.useRealTimers()
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
    expect(
      await screen.findByText('Placed: records per week (week): Recorded[2026-10-05=2 2026-10-12=0 2026-10-19=1]'),
    ).toBeInTheDocument()
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

  it('marks the period still running as so far, so its drop is not read as a fall', () => {
    expect(unfinished('2026-10-12', 'week', '2026-10-14')).toBe(true)
    expect(unfinished('2026-10-12', 'week', '2026-10-19')).toBe(false)
    expect(unfinished('2026-10-01', 'month', '2026-10-31')).toBe(true)
    const rows = (counts: Record<string, number>) => ({
      rows: Object.entries(counts).map(([at, n]) => ({ group: { placed: at }, metrics: { n } })),
      scan_truncated: false,
    })
    const [running] = countSeries(rows(WEEKS), 'placed', 'week', '2026-10-21')
    // ITS OWN POINT, which the chart draws hollow and does not join to the
    // line: a line down to half a week's count reads as a fall.
    expect(running!.points.map((point) => point.partial === true)).toEqual([false, false, true])
    const [finished] = countSeries(rows(WEEKS), 'placed', 'week', '2027-01-01')
    expect(finished!.points.some((point) => point.partial)).toBe(false)
  })

  it('is drawn with the period it was asked for, on its first line the recorded counts', async () => {
    show()
    await screen.findByText(/records per week \(week\)/)
    fireEvent.click(screen.getByRole('button', { name: 'Month' }))
    expect(await screen.findByText(/records per month \(month\)/)).toBeInTheDocument()
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
    await screen.findByText(/records per week \(week\)/)
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
    await screen.findByText(/records per week \(week\)/)
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
    await screen.findByText(/records per week \(week\)/)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Forecast' }))
    expect(await screen.findByText('No forecast: it missed by as much as carrying on.')).toBeInTheDocument()
    expect(screen.queryByText(/with a forecast/)).not.toBeInTheDocument()
  })

  it('draws the recorded counts, and the forecast dashed beside them', async () => {
    forecastObjects.mockResolvedValue(FORECAST)
    show()
    await screen.findByText(/records per week \(week\):/)
    fireEvent.click(screen.getByRole('checkbox', { name: 'Forecast' }))
    expect(
      await screen.findByText(
        'Placed: records per week, with a forecast (week): ' +
          'Recorded[2026-09-28=40 2026-10-05=50 2026-10-12=32*] ' +
          'Forecast dashed[2026-10-05=50 2026-10-12=45 2026-10-19=46]',
      ),
    ).toBeInTheDocument()
  })

  it('is one quantity: dashed, in the recorded colour, anchored on the last finished period', () => {
    const [recorded, forecast] = forecastSeries(FORECAST)
    expect(forecast).toMatchObject({ dashed: true, sameColourAs: recorded!.name, band: '80% range' })
    // ANCHORED, so the dashes leave the line rather than starting beside it.
    expect(forecast!.points[0]).toEqual({ at: '2026-10-05', value: 50, low: 50, high: 50 })
    expect(forecast!.points.slice(1)).toEqual([
      { at: '2026-10-12', value: 45, low: 40, high: 50 },
      { at: '2026-10-19', value: 46, low: 39, high: 53 },
    ])
    expect(recorded!.points.at(-1)).toEqual({ at: '2026-10-12', value: 32, partial: true })
  })

  it('tells the running period, its forecast and the range as the two edges', () => {
    const option = timeChartOption(forecastSeries(FORECAST), { colors: ['#000'], grain: 'week' }) as unknown as {
      tooltip: { formatter: (params: unknown[]) => string }
    }
    const at = Date.parse('2026-10-12')
    const tip = option.tooltip.formatter([
      { seriesName: 'Recorded so far', axisValue: at, value: [at, 32] },
      { seriesName: 'Forecast', axisValue: at, value: [at, 45] },
      { seriesName: '80% range floor', axisValue: at, value: [at, 40] },
      { seriesName: '80% range', axisValue: at, value: [at, 10] },
    ])
    expect(tip).toContain('Recorded so far: 32<br/>Forecast: 45<br/>80% range: 40 to 50')
    expect(tip).toMatch(/^Week of /)
  })
})
