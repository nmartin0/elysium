/**
 * timeChart.ts -- values over time, as an ECharts option.
 *
 * THE KIT'S ONE TIME CHART, promoted from Browse's over-time chart so a
 * module charts a time series the same way and none writes its own. It
 * is a pure function from series to option, with no React and no
 * canvas in it, so what it draws is tested as data (a canvas jsdom
 * cannot read).
 *
 * A TIME AXIS, NOT A CATEGORY ONE. Points sit where their time puts
 * them: an hour missing from the data is a gap of an hour, not
 * a neighbour, and a series of quarter-hours and one of days can share an
 * axis. The category axis this replaces spaced whatever it was given
 * evenly, which is only true of buckets that happen to be.
 *
 * SEVERAL LINES, solid or dashed, each on the left axis or a second one
 * on the right -- a count and a total do not share a scale. Lines that
 * are one quantity (recorded and forecast) share a colour, told apart by
 * dashes and the legend, never by colour alone.
 *
 * A POINT STILL BEING COUNTED (`partial`) is drawn hollow and NOT JOINED:
 * this week's count on a Wednesday is half a week's, and joined to the
 * line it reads as a fall that has not happened.
 *
 * A RANGE (`low` and `high` on a series' points, named by `band`) is a
 * wash behind the line, drawn as a stack: an invisible floor and the
 * spread above it.
 *
 * ZOOM: the wheel and a drag inside the plot, and a slider under it once
 * there are enough points to want one.
 *
 * TIME ZONES: a date (2026-05-04) is a day, not an instant, and is
 * drawn on that day wherever the reader is. An instant is drawn on the
 * reader's own clock; ECharts cannot draw another zone's.
 */

import type { AggregateResult } from './api'

export type TimeGrain = 'day' | 'week' | 'month'

export interface TimePoint {
  /** An ISO 8601 date (a day) or instant. */
  at: string
  value: number | null
  /** The range around the value, for a series with a `band`. */
  low?: number
  high?: number
  /** Still being counted: hollow, and not joined to the line. */
  partial?: boolean
}

export interface TimeSeries {
  name: string
  points: TimePoint[]
  dashed?: boolean
  /** Which value axis; the left by default. */
  axis?: 'left' | 'right'
  /** Names the range drawn from the points' `low` and `high`. */
  band?: string
  /** Draws in the colour of the series of this name, as a continuation. */
  sameColourAs?: string
}

export interface TimeChartOptions {
  /** The palette, in order; a series takes the next unused. */
  colors: readonly string[]
  /** How a point's period is named in the tooltip. Without one, a point
   *  is named by its date (and time, for an instant). */
  grain?: TimeGrain
  axisNames?: { left?: string; right?: string }
}

/** Past this many distinct times a slider is worth its height. */
export const SLIDER_FROM = 12

/** Past this many points, a marker on each is clutter. */
const MARKERS_UP_TO = 24

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/

function escapeHtml(text: string): string {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

/** A point's name in a tooltip. */
export function timeLabel(ms: number, utc: boolean, grain?: TimeGrain): string {
  const zone = utc ? 'UTC' : undefined
  const day = new Date(ms).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: zone,
  })
  if (grain === 'month') {
    return new Date(ms).toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: zone })
  }
  if (grain === 'week') return `Week of ${day}`
  if (grain === 'day' || utc) return day
  return new Date(ms).toLocaleString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function shown(value: number): string {
  return String(Number(value.toFixed(2)))
}

interface Plotted {
  ms: number
  point: TimePoint
}

function plotted(points: TimePoint[]): Plotted[] {
  return points
    .map((point) => ({ ms: Date.parse(point.at), point }))
    .filter((entry) => Number.isFinite(entry.ms))
    .sort((a, b) => a.ms - b.ms)
}

export function timeChartOption(series: TimeSeries[], options: TimeChartOptions): Record<string, unknown> {
  const utc = series.length > 0 && series.every((entry) => entry.points.every((point) => DATE_ONLY.test(point.at)))
  const hasRight = series.some((entry) => entry.axis === 'right')

  // One colour per quantity: a continuation takes its original's.
  const colourOf = new Map<string, string>()
  for (const entry of series) {
    const group = entry.sameColourAs ?? entry.name
    if (!colourOf.has(group)) colourOf.set(group, options.colors[colourOf.size % options.colors.length] ?? '#4c6ef5')
  }

  const times = new Set<number>()
  const ranges = new Map<string, { low: number; high: number }>()
  const legend: string[] = []
  const lines: Record<string, unknown>[] = []

  series.forEach((entry, index) => {
    const colour = colourOf.get(entry.sameColourAs ?? entry.name)!
    const yAxisIndex = entry.axis === 'right' ? 1 : 0
    const all = plotted(entry.points)
    all.forEach(({ ms }) => times.add(ms))
    const joined = all.filter(({ point }) => !point.partial)
    const unfinished = all.filter(({ point }) => point.partial)

    legend.push(entry.name)
    lines.push({
      type: 'line',
      name: entry.name,
      yAxisIndex,
      data: joined.map(({ ms, point }) => [ms, point.value]),
      lineStyle: { width: 2, cap: 'round', join: 'round', type: entry.dashed ? 'dashed' : 'solid', color: colour },
      itemStyle: { color: colour },
      symbol: 'circle',
      symbolSize: 8,
      showSymbol: all.length <= MARKERS_UP_TO && !entry.dashed,
      z: entry.dashed ? 2 : 3,
    })

    if (unfinished.length > 0) {
      const name = `${entry.name} so far`
      legend.push(name)
      lines.push({
        type: 'line',
        name,
        yAxisIndex,
        data: unfinished.map(({ ms, point }) => [ms, point.value]),
        symbol: 'emptyCircle',
        symbolSize: 9,
        showSymbol: true,
        // NEVER THINNED: on a long axis ECharts hides points at
        // intervals, and this one fell on a skipped one -- found in the
        // browser, with the legend naming a point that was not there.
        showAllSymbol: true,
        lineStyle: { width: 0, color: colour },
        itemStyle: { color: colour },
        z: 4,
      })
    }

    const banded =
      entry.band === undefined ? [] : all.filter(({ point }) => point.low !== undefined && point.high !== undefined)
    if (entry.band !== undefined && banded.length > 0) {
      legend.push(entry.band)
      const stack = `band-${index}`
      lines.push({
        type: 'line',
        name: `${entry.band} floor`,
        yAxisIndex,
        stack,
        data: banded.map(({ ms, point }) => [ms, point.low]),
        lineStyle: { opacity: 0 },
        showSymbol: false,
        tooltip: { show: false },
        silent: true,
      })
      lines.push({
        type: 'line',
        name: entry.band,
        yAxisIndex,
        stack,
        data: banded.map(({ ms, point }) => [ms, (point.high as number) - (point.low as number)]),
        lineStyle: { opacity: 0 },
        // A wash, not a block -- stronger than a light theme's 10% so it
        // still reads on a dark surface.
        areaStyle: { opacity: 0.2, color: colour },
        // The legend's swatch for the range: the line's colour, not the next one.
        itemStyle: { color: colour },
        showSymbol: false,
        silent: true,
      })
      for (const { ms, point } of banded) {
        ranges.set(`${entry.band}|${ms}`, { low: point.low as number, high: point.high as number })
      }
    }
  })

  const slider = times.size > SLIDER_FROM
  return {
    useUTC: utc,
    grid: {
      left: 8,
      right: hasRight ? 16 : 24,
      top: legend.length > 1 ? 32 : 16,
      bottom: slider ? 44 : 8,
      containLabel: true,
    },
    ...(legend.length > 1 ? { legend: { top: 0, data: legend } } : {}),
    xAxis: { type: 'time', boundaryGap: false, axisLabel: { hideOverlap: true } },
    yAxis: [
      { type: 'value', ...(options.axisNames?.left ? { name: options.axisNames.left } : {}) },
      ...(hasRight
        ? [
            {
              type: 'value',
              position: 'right',
              splitLine: { show: false },
              ...(options.axisNames?.right ? { name: options.axisNames.right } : {}),
            },
          ]
        : []),
    ],
    dataZoom: [
      { type: 'inside', filterMode: 'none' },
      ...(slider ? [{ type: 'slider', height: 18, bottom: 8, filterMode: 'none' }] : []),
    ],
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      // BY NAME AND VALUE, with a range as its two edges: the stacked
      // series hold its floor and its width, neither of which a reader
      // asked for. Names are escaped: they are labels from configuration.
      formatter: (params: { seriesName: string; axisValue: number; value: [number, number | null] }[]) => {
        const first = params[0]
        if (first === undefined) return ''
        const rows = [escapeHtml(timeLabel(first.axisValue, utc, options.grain))]
        for (const param of params) {
          if (param.seriesName.endsWith(' floor')) continue
          const range = ranges.get(`${param.seriesName}|${param.value[0]}`)
          if (range !== undefined) {
            rows.push(`${escapeHtml(param.seriesName)}: ${shown(range.low)} to ${shown(range.high)}`)
            continue
          }
          const value = param.value[1]
          if (value === null || value === undefined) continue
          rows.push(`${escapeHtml(param.seriesName)}: ${shown(value)}`)
        }
        return rows.join('<br/>')
      },
    },
    series: lines,
  }
}

/** An aggregate's rows as lines over time: one series per measure, a
 *  point per row, in the order the server sent them. */
export function seriesFromRows(
  result: AggregateResult,
  groupBy: string,
  measures: { name: string; label: string; axis?: 'left' | 'right' }[],
): TimeSeries[] {
  return measures.map((measure) => ({
    name: measure.label,
    ...(measure.axis ? { axis: measure.axis } : {}),
    points: result.rows.map((row) => {
      const value = row.metrics[measure.name]
      return { at: String(row.group[groupBy]), value: typeof value === 'number' ? value : null }
    }),
  }))
}
