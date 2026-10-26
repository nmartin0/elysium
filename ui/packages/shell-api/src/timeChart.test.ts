import { describe, expect, it } from 'vitest'

import type { AggregateResult } from './api'
import { SLIDER_FROM, seriesFromRows, timeChartOption, timeLabel, type TimeSeries } from './timeChart'

const COLORS = ['#111111', '#222222', '#333333']
const DAY = 86_400_000

type Line = {
  name: string
  data: [number, number | null][]
  yAxisIndex: number
  lineStyle: { type?: string; width?: number; color?: string; opacity?: number }
  itemStyle?: { color: string }
  areaStyle?: { opacity: number; color: string }
  stack?: string
  symbol?: string
}
type Option = {
  useUTC: boolean
  legend?: { data: string[] }
  xAxis: { type: string }
  yAxis: { type: string; position?: string; name?: string }[]
  dataZoom: { type: string }[]
  series: Line[]
  tooltip: { formatter: (params: unknown[]) => string }
}

const build = (series: TimeSeries[], extra = {}) =>
  timeChartOption(series, { colors: COLORS, ...extra }) as unknown as Option

const days = (count: number, from = '2026-05-01') =>
  Array.from({ length: count }, (_, index) => ({
    at: new Date(Date.parse(from) + index * DAY).toISOString().slice(0, 10),
    value: index,
  }))

describe('the time axis', () => {
  it('places points by their time, in time order, whatever order they came in', () => {
    const option = build([
      {
        name: 'Orders',
        points: [
          { at: '2026-05-11', value: 3 },
          { at: '2026-05-04', value: 5 },
        ],
      },
    ])

    expect(option.xAxis.type).toBe('time')
    expect(option.series[0]?.data).toEqual([
      [Date.parse('2026-05-04'), 5],
      [Date.parse('2026-05-11'), 3],
    ])
  })

  it('keeps a gap as a gap, and drops a point with no time', () => {
    const option = build([
      {
        name: 'Orders',
        points: [
          { at: '2026-05-04', value: 5 },
          { at: '2026-05-11', value: null },
          { at: 'not a time', value: 9 },
        ],
      },
    ])

    expect(option.series[0]?.data).toEqual([
      [Date.parse('2026-05-04'), 5],
      [Date.parse('2026-05-11'), null],
    ])
  })

  it('draws a date on its own day wherever the reader is, and an instant on their clock', () => {
    expect(build([{ name: 'a', points: [{ at: '2026-05-04', value: 1 }] }]).useUTC).toBe(true)
    expect(build([{ name: 'a', points: [{ at: '2026-05-04T10:00:00+01:00', value: 1 }] }]).useUTC).toBe(false)
  })

  it('names a point by its period', () => {
    const may = Date.parse('2026-05-04')
    expect(timeLabel(may, true, 'week')).toMatch(/^Week of .*2026/)
    expect(timeLabel(may, true, 'month')).not.toMatch(/\b4\b/)
    expect(timeLabel(may, true, 'day')).toMatch(/4/)
  })
})

describe('several lines', () => {
  const two: TimeSeries[] = [
    { name: 'Orders', points: days(3) },
    { name: 'Revenue', axis: 'right', points: days(3) },
  ]

  it('has a legend only when there is more than one thing to tell apart', () => {
    expect(build([two[0]!]).legend).toBeUndefined()
    expect(build(two).legend?.data).toEqual(['Orders', 'Revenue'])
  })

  it('puts a series on a second axis only when asked, and only then has one', () => {
    const option = build(two)
    expect(option.yAxis).toHaveLength(2)
    expect(option.yAxis[1]?.position).toBe('right')
    expect(option.series.map((line) => line.yAxisIndex)).toEqual([0, 1])
    expect(build([two[0]!]).yAxis).toHaveLength(1)
  })

  it('names the axes it was told to', () => {
    expect(build(two, { axisNames: { left: 'Orders', right: '£' } }).yAxis.map((axis) => axis.name)).toEqual([
      'Orders',
      '£',
    ])
  })

  it('gives each quantity its own colour', () => {
    const option = build(two)
    expect(option.series.map((line) => line.lineStyle.color)).toEqual(['#111111', '#222222'])
  })

  it('draws a continuation dashed, in its original colour', () => {
    const option = build([
      { name: 'Recorded', points: days(3) },
      { name: 'Forecast', dashed: true, sameColourAs: 'Recorded', points: days(3, '2026-05-03') },
      { name: 'Other', points: days(3) },
    ])

    expect(option.series[1]?.lineStyle.type).toBe('dashed')
    expect(option.series[1]?.lineStyle.color).toBe(option.series[0]?.lineStyle.color)
    // The colour a continuation shares is not used up.
    expect(option.series[2]?.lineStyle.color).toBe('#222222')
  })
})

describe('a point still being counted', () => {
  const series: TimeSeries[] = [
    {
      name: 'Orders',
      points: [
        { at: '2026-05-04', value: 5 },
        { at: '2026-05-11', value: 2, partial: true },
      ],
    },
  ]

  it('is left off the line and drawn hollow on its own', () => {
    const option = build(series)

    expect(option.series[0]?.data).toEqual([[Date.parse('2026-05-04'), 5]])
    expect(option.series[1]?.name).toBe('Orders so far')
    expect(option.series[1]?.symbol).toBe('emptyCircle')
    expect(option.series[1]?.lineStyle.width).toBe(0)
    expect(option.series[1]?.data).toEqual([[Date.parse('2026-05-11'), 2]])
  })

  it('is named in the legend, since nothing else says what the hollow point is', () => {
    expect(build(series).legend?.data).toEqual(['Orders', 'Orders so far'])
  })
})

describe('a range around a line', () => {
  const series: TimeSeries[] = [
    {
      name: 'Forecast',
      band: '80% range',
      points: [
        { at: '2026-05-04', value: 10, low: 10, high: 10 },
        { at: '2026-05-11', value: 12, low: 8, high: 17 },
      ],
    },
  ]

  it('is an invisible floor with the spread washed in above it', () => {
    const option = build(series)
    const [, floor, spread] = option.series

    expect(floor?.name).toBe('80% range floor')
    expect(floor?.lineStyle.opacity).toBe(0)
    expect(floor?.data.map(([, value]) => value)).toEqual([10, 8])
    expect(spread?.name).toBe('80% range')
    expect(spread?.data.map(([, value]) => value)).toEqual([0, 9])
    expect(spread?.areaStyle?.opacity).toBe(0.2)
    expect(floor?.stack).toBe(spread?.stack)
  })

  it("is drawn in its line's colour, in the plot and in the legend", () => {
    const [line, , spread] = build(series).series

    expect(spread?.areaStyle?.color).toBe(line?.lineStyle.color)
    expect(spread?.itemStyle?.color).toBe(line?.lineStyle.color)
  })

  it('is named in the legend, and its floor is not', () => {
    expect(build(series).legend?.data).toEqual(['Forecast', '80% range'])
  })

  it('is told in the tooltip as its two edges', () => {
    const text = build(series).tooltip.formatter([
      { seriesName: 'Forecast', axisValue: Date.parse('2026-05-11'), value: [Date.parse('2026-05-11'), 12] },
      { seriesName: '80% range floor', axisValue: Date.parse('2026-05-11'), value: [Date.parse('2026-05-11'), 8] },
      { seriesName: '80% range', axisValue: Date.parse('2026-05-11'), value: [Date.parse('2026-05-11'), 9] },
    ])

    expect(text).toContain('Forecast: 12')
    expect(text).toContain('80% range: 8 to 17')
    expect(text).not.toContain('floor')
  })
})

describe('the tooltip', () => {
  it('escapes a series name, which is a label from configuration', () => {
    const option = build([{ name: '<img src=x onerror=alert(1)>', points: days(2) }])
    const at = Date.parse('2026-05-01')
    const text = option.tooltip.formatter([
      { seriesName: '<img src=x onerror=alert(1)>', axisValue: at, value: [at, 0] },
    ])

    expect(text).not.toContain('<img')
    expect(text).toContain('&lt;img')
  })

  it('leaves out a series with nothing at that time', () => {
    const option = build([{ name: 'Orders', points: days(2) }])
    const at = Date.parse('2026-05-01')

    expect(option.tooltip.formatter([{ seriesName: 'Orders', axisValue: at, value: [at, null] }])).not.toContain(
      'Orders',
    )
  })

  it('rounds to two places', () => {
    const option = build([{ name: 'Orders', points: days(2) }])
    const at = Date.parse('2026-05-01')

    expect(option.tooltip.formatter([{ seriesName: 'Orders', axisValue: at, value: [at, 1 / 3] }])).toContain(
      'Orders: 0.33',
    )
  })
})

describe('zoom', () => {
  it('is always there inside the plot, and has a slider only once there is enough to want one', () => {
    expect(build([{ name: 'a', points: days(SLIDER_FROM) }]).dataZoom.map((zoom) => zoom.type)).toEqual(['inside'])
    expect(build([{ name: 'a', points: days(SLIDER_FROM + 1) }]).dataZoom.map((zoom) => zoom.type)).toEqual([
      'inside',
      'slider',
    ])
  })
})

describe('seriesFromRows', () => {
  const result: AggregateResult = {
    rows: [
      { group: { day: '2026-05-04' }, metrics: { n: 2, total: 10.5 } },
      { group: { day: '2026-05-11' }, metrics: { n: 0, total: null } },
    ],
    scan_truncated: false,
  }

  it('makes a line per measure, in the order the rows came, with null kept as null', () => {
    expect(
      seriesFromRows(result, 'day', [
        { name: 'n', label: 'Orders' },
        { name: 'total', label: 'Revenue', axis: 'right' },
      ]),
    ).toEqual([
      {
        name: 'Orders',
        points: [
          { at: '2026-05-04', value: 2 },
          { at: '2026-05-11', value: 0 },
        ],
      },
      {
        name: 'Revenue',
        axis: 'right',
        points: [
          { at: '2026-05-04', value: 10.5 },
          { at: '2026-05-11', value: null },
        ],
      },
    ])
  })
})
