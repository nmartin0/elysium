/**
 * aggregateCharts.ts -- aggregate results as chart options.
 *
 * /aggregate answers with {group: metric}. Turning that into an
 * ECharts option is arithmetic and naming, with no React and no
 * network in it -- so it lives here as plain functions rather than
 * inside a component. A component would make these testable only
 * through a canvas that jsdom cannot read.
 *
 * FOUR SHAPES, chosen because they answer different questions:
 *
 *   value counts   how many objects per value, ranked. The workhorse:
 *                  "which regions do my customers sit in".
 *   histogram      the same data unranked, in the field's own order,
 *                  for values that mean something in sequence.
 *   pie            proportion rather than count, for a handful of
 *                  buckets. Useless past about six, so it says so.
 *   statistic      one number over the whole set, when there is no
 *                  grouping field worth splitting by.
 *
 * NAMES ARE OURS, not the reference implementation's. "Listogram" is
 * jargon nobody outside Foundry knows; "value counts" describes it.
 */

import type { AggregateResult } from '@elysium/shell-api/api'
import { seriesFromRows, type TimeSeries } from '@elysium/shell-api/timeChart'

export interface AggregateResults {
  [group: string]: number
}

/** Past this, a pie is a colour wheel rather than a comparison. */
export const PIE_MAX_SLICES = 6

/** Bars beyond this crowd out their own labels; the rest become an
 *  "other" bucket rather than being silently dropped. */
export const MAX_BARS = 12

function sortedEntries(results: AggregateResults): [string, number][] {
  return Object.entries(results).sort(([, a], [, b]) => b - a)
}

/**
 * Groups beyond the limit, folded into one bucket.
 *
 * Folded rather than dropped: a chart that silently omits the tail
 * misrepresents the total, and someone reading "50 in us-west" out of
 * 200 objects should be able to see that the rest exist.
 */
function withOther(entries: [string, number][], limit: number): [string, number][] {
  if (entries.length <= limit) return entries
  const kept = entries.slice(0, limit)
  const rest = entries.slice(limit).reduce((sum, [, value]) => sum + value, 0)
  return [...kept, [`Other (${entries.length - limit})`, rest]]
}

export function valueCountsOption(
  results: AggregateResults,
  { selected = [], excluded = [] }: { selected?: string[]; excluded?: string[] } = {},
): Record<string, unknown> {
  const entries = withOther(sortedEntries(results), MAX_BARS)
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value' },
    // Reversed because ECharts draws a category axis bottom-up, and a
    // ranked list reads top-down.
    yAxis: { type: 'category', data: entries.map(([name]) => name).reverse() },
    tooltip: { trigger: 'item' },
    series: [
      {
        type: 'bar',
        data: entries
          .map(([name, value]) => ({
            name,
            value,
            // Selection is shown by DIMMING the rest rather than hiding
            // it: a filtered-out bar still tells you how much you filtered
            // away, and a chart whose bars vanish on click loses the
            // context that made the click sensible.
            itemStyle: {
              opacity: dimmed(name, selected, excluded) ? 0.3 : 1,
            },
          }))
          .reverse(),
      },
    ],
  }
}

/** How many ranges a number's distribution is folded into. */
const HISTOGRAM_BINS = 10

function tidy(n: number): string {
  return String(Number(n.toPrecision(3)))
}

/**
 * A NUMBER'S COUNTS BY VALUE, FOLDED INTO EQUAL RANGES, in numeric order.
 *
 * Counting a number value by value is a list of distinct values, not a
 * distribution: 190 amounts became "199, 49.99, 10, 11, 12 ... Other
 * (190)" -- found in a browser. Null when there is nothing to fold (no
 * number, or one value), so the caller keeps the plain chart. A value
 * that is not a number (a missing one) is counted apart, as "No value",
 * rather than dropped, so the bars still add up to the set.
 */
export function binnedCounts(
  results: AggregateResults,
  bins = HISTOGRAM_BINS,
): { label: string; count: number }[] | null {
  const numeric: [number, number][] = []
  let missing = 0
  for (const [key, count] of Object.entries(results)) {
    const n = Number(key)
    if (key.trim() === '' || !Number.isFinite(n)) missing += count
    else numeric.push([n, count])
  }
  if (numeric.length === 0) return null
  const values = numeric.map(([n]) => n)
  const low = Math.min(...values)
  const high = Math.max(...values)
  if (low === high) return null
  const width = (high - low) / bins
  const counts = Array.from({ length: bins }, () => 0)
  for (const [n, count] of numeric) counts[Math.min(bins - 1, Math.floor((n - low) / width))]! += count
  const ranges = counts.map((count, index) => ({
    label: `${tidy(low + index * width)}\u2013${tidy(low + (index + 1) * width)}`,
    count,
  }))
  return missing > 0 ? [...ranges, { label: 'No value', count: missing }] : ranges
}

/** The folded counts as horizontal bars, smallest range first, top-down. */
export function binnedOption(ranges: { label: string; count: number }[]): Record<string, unknown> {
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'value' },
    yAxis: { type: 'category', data: ranges.map(({ label }) => label).reverse() },
    tooltip: { trigger: 'item' },
    series: [{ type: 'bar', data: ranges.map(({ label, count }) => ({ name: label, value: count })).reverse() }],
  }
}

export function histogramOption(results: AggregateResults): Record<string, unknown> {
  // The field's OWN order, not by count -- a histogram over buckets
  // that mean something in sequence (dates, amounts) is unreadable
  // ranked.
  const entries = Object.entries(results).sort(([a], [b]) => a.localeCompare(b))
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: 'category', data: entries.map(([name]) => name) },
    yAxis: { type: 'value' },
    tooltip: { trigger: 'item' },
    series: [{ type: 'bar', data: entries.map(([name, value]) => ({ name, value })) }],
  }
}

export function pieOption(results: AggregateResults): Record<string, unknown> {
  const entries = withOther(sortedEntries(results), PIE_MAX_SLICES)
  return {
    tooltip: { trigger: 'item' },
    legend: { type: 'scroll', bottom: 0 },
    series: [
      {
        type: 'pie',
        // A SMALLER RING AND NO LABEL ON A SLICE TOO THIN TO HOLD ONE.
        // Three thin slices put three names on top of each other and over
        // the legend; the legend and the tooltip name every slice anyway.
        radius: ['35%', '60%'],
        center: ['50%', '45%'],
        minShowLabelAngle: 12,
        labelLayout: { hideOverlap: true },
        data: entries.map(([name, value]) => ({ name, value })),
      },
    ],
  }
}

function dimmed(name: string, selected: string[], excluded: string[]): boolean {
  if (excluded.includes(name)) return true
  return selected.length > 0 && !selected.includes(name)
}

/**
 * Whether a set of results is worth drawing as a pie.
 *
 * A pie with thirty slices is a colour wheel. Callers ask first and
 * offer a different shape rather than rendering something unreadable
 * and letting the user work out why.
 */
export function suitsAPie(results: AggregateResults): boolean {
  const groups = Object.keys(results).length
  return groups > 1 && groups <= PIE_MAX_SLICES
}

/**
 * One field's chart selection.
 *
 * `mode` is keep or exclude, which is what makes chart-filtering more
 * than a fancy dropdown: "everything except these three" is a question
 * people actually ask, and a picker cannot express it.
 */
export interface ChartFilter {
  field: string
  values: string[]
  mode: 'keep' | 'exclude'
}

/**
 * Chart selections as filter conditions.
 *
 * `in` and `not_in`, which the vocabulary already has -- no widening
 * was needed for click-to-filter, because selecting several values on
 * one chart is exactly set membership.
 *
 * Fields AND together, matching how the conditions themselves combine.
 * Two selections on two charts narrow; they do not union.
 */
export function asConditions(filters: ChartFilter[]): unknown[] {
  return filters
    .filter((filter) => filter.values.length > 0)
    .map((filter) => ({
      field: filter.field,
      operator: filter.mode === 'exclude' ? 'not_in' : 'in',
      value: filter.values,
    }))
}

/**
 * Conditions back as chart filters -- `asConditions` reversed.
 *
 * WHY THE REVERSE EXISTS AT ALL. The URL's `filters` key speaks
 * ChartFilter (`{field, values, mode}`) and the API speaks conditions
 * (`{field, operator, value}`). A saved view stores conditions, so
 * rebuilding its URL means translating back.
 *
 * ONLY `in` AND `not_in` SURVIVE, and that is the honest limit rather
 * than an oversight. Those are the only two `asConditions` produces,
 * so they are the only two a view saved from a URL can contain; a
 * `range` condition written by some other route has no ChartFilter
 * that means the same thing, and inventing one would put a filter on
 * screen that narrows differently from the one that was saved.
 * Anything else is dropped here and the caller decides what to say.
 */
export function asChartFilters(conditions: unknown[]): ChartFilter[] {
  const filters: ChartFilter[] = []
  for (const condition of conditions) {
    if (condition === null || typeof condition !== 'object') continue
    const { field, operator, value } = condition as Record<string, unknown>
    if (typeof field !== 'string') continue
    if (operator !== 'in' && operator !== 'not_in') continue
    if (!Array.isArray(value)) continue
    filters.push({
      field,
      values: value.map((each) => String(each)),
      mode: operator === 'not_in' ? 'exclude' : 'keep',
    })
  }
  return filters
}

/** The values selected on one field's chart, for dimming the rest. */
export function selectionFor(
  filters: ChartFilter[],
  field: string,
): {
  selected: string[]
  excluded: string[]
} {
  const filter = filters.find((entry) => entry.field === field)
  if (filter === undefined) return { selected: [], excluded: [] }
  return filter.mode === 'exclude'
    ? { selected: [], excluded: filter.values }
    : { selected: filter.values, excluded: [] }
}

/**
 * The filter to aggregate ONE field's chart under -- everything
 * except that field's own selection.
 *
 * A CHART DOES NOT FILTER ITSELF, which is the rule every
 * cross-filtering tool follows and the one this originally got wrong.
 * Clicking "us-west" on the region chart filtered the region chart to
 * us-west, leaving it with a single value; the panel then dropped it
 * as having nothing to show, and every chart vanished on the first
 * click.
 *
 * Excluding a field's own selection keeps its other bars on screen,
 * which is what makes the dimming meaningful: you can see what you
 * chose, what you did not, and how much you filtered away -- and click
 * a different bar without first undoing the last one.
 */
export function conditionsExcluding(filters: ChartFilter[], field: string): unknown[] {
  return asConditions(filters.filter((filter) => filter.field !== field))
}

/** The day after a period ends, as an ISO date (UTC). */
function periodEnd(start: string, period: 'day' | 'week' | 'month'): string {
  const date = new Date(`${start}T00:00:00Z`)
  if (period === 'day') date.setUTCDate(date.getUTCDate() + 1)
  else if (period === 'week') date.setUTCDate(date.getUTCDate() + 7)
  else date.setUTCMonth(date.getUTCMonth() + 1)
  return date.toISOString().slice(0, 10)
}

/** Whether a period has not finished yet on `today` (an ISO date, UTC):
 *  its total is so far, not final. */
export function unfinished(start: string, period: 'day' | 'week' | 'month', today: string): boolean {
  return periodEnd(start, period) > today
}

/**
 * A total per period, as the kit's time chart takes it (R68): one line,
 * recorded.
 *
 * THE PERIOD STILL RUNNING IS PARTIAL: this week's count on a Wednesday
 * is half a week's, and drawn like the others it reads as a fall that
 * has not happened. The chart draws it hollow and does not join it.
 * `today` is an ISO date, UTC, as the server buckets.
 */
export function countSeries(
  result: AggregateResult,
  field: string,
  period: 'day' | 'week' | 'month',
  today: string = new Date().toISOString().slice(0, 10),
): TimeSeries[] {
  const [series] = seriesFromRows(result, field, [{ name: 'n', label: 'Recorded' }])
  return (series ? [series] : []).map((line) => ({
    ...line,
    points: line.points.map((point) => (unfinished(point.at, period, today) ? { ...point, partial: true } : point)),
  }))
}

export interface ForecastShape {
  history: Record<string, number>
  running: { start: string; value: number } | null
  points: { start: string; value: number; low: number; high: number }[]
}

/**
 * The recorded totals and where they are heading (R68), as lines.
 *
 * THE PROJECTION IS DASHED -- the one meaning a dashed line keeps on these
 * charts -- and starts from the last finished period, so it reads as a
 * continuation rather than a second series. THE BAND is the 80% range;
 * the period still running stays a hollow point on the recorded line,
 * beside the projection of where it will finish. ONE COLOUR for the
 * two: they are one quantity, recorded and projected.
 */
export function forecastSeries(forecast: ForecastShape): TimeSeries[] {
  const finished = Object.keys(forecast.history).sort()
  const last = finished.at(-1)
  // ANCHORED on the last finished period, so the dashes leave the line.
  const anchor =
    last === undefined
      ? []
      : [
          {
            at: last,
            value: forecast.history[last] ?? 0,
            low: forecast.history[last] ?? 0,
            high: forecast.history[last] ?? 0,
          },
        ]
  return [
    {
      name: 'Recorded',
      points: [
        ...finished.map((at) => ({ at, value: forecast.history[at] ?? null })),
        ...(forecast.running ? [{ at: forecast.running.start, value: forecast.running.value, partial: true }] : []),
      ],
    },
    {
      name: 'Forecast',
      dashed: true,
      sameColourAs: 'Recorded',
      band: '80% range',
      points: [
        ...anchor,
        ...forecast.points.map((point) => ({ at: point.start, value: point.value, low: point.low, high: point.high })),
      ],
    },
  ]
}
