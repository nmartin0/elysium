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
        radius: ['40%', '70%'],
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

/** How a period is named on the axis: by the day it starts, at the
 *  precision the period has. UTC, as the server buckets in UTC. */
export function periodLabel(start: string, period: 'day' | 'week' | 'month'): string {
  const date = new Date(`${start}T00:00:00Z`)
  if (Number.isNaN(date.getTime())) return start
  if (period === 'month') {
    return date.toLocaleDateString(undefined, { month: 'short', year: 'numeric', timeZone: 'UTC' })
  }
  const day = date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
  return period === 'week' ? `Week of ${day}` : day
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
 * A total per period, as a line over time (R68).
 *
 * A LINE, NOT BARS: a series over time is read as a shape -- rising,
 * flat, seasonal -- and a hundred thin columns hide it. In the
 * period's own order, which the ISO keys sort into.
 *
 * A CROSSHAIR, NOT A POINT TOOLTIP: on a line the reader asks "what was
 * it then", so the tooltip follows the axis, not the nearest mark.
 * Points are drawn only when there are few enough to see one by one.
 *
 * THE PERIOD STILL RUNNING IS MARKED "so far": this week's count on a
 * Wednesday is half a week's, and drawn like the others it reads as a
 * fall that has not happened. Its point is hollow, and the axis and
 * tooltip say so.
 */
export function overTimeOption(
  results: AggregateResults,
  period: 'day' | 'week' | 'month',
  today: string = new Date().toISOString().slice(0, 10),
): Record<string, unknown> {
  const entries = Object.entries(results).sort(([a], [b]) => a.localeCompare(b))
  const running = entries.findIndex(([start]) => unfinished(start, period, today))
  return {
    // The running period is the same quantity, unfinished: same colour.
    oneColour: true,
    grid: { left: 8, right: 24, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: entries.map(([start], index) =>
        index === running ? `${periodLabel(start, period)} (so far)` : periodLabel(start, period),
      ),
      // The axis names a week by its first day; the tooltip says "Week of".
      axisLabel: { hideOverlap: true, formatter: (label: string) => label.replace(/^Week of /, '') },
    },
    yAxis: { type: 'value' },
    tooltip: { trigger: 'axis', axisPointer: { type: 'line' } },
    series: [
      {
        type: 'line',
        name: 'Recorded',
        // (ECharts' own default marker is hollow, hence `circle`.)
        data: entries.map(([, value], index) => (index === running ? null : value)),
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        symbol: 'circle',
        showSymbol: entries.length <= 24,
        symbolSize: 8,
      },
      ...(running >= 0 ? [soFar(entries.map(([, value], index) => (index === running ? value : null)))] : []),
    ],
  }
}

/** The period still running, as its own point: hollow, NOT JOINED to the
 *  line -- a line down to half a week's count reads as a fall -- and
 *  drawn however many periods there are. */
function soFar(data: (number | null)[]): Record<string, unknown> {
  return {
    type: 'line',
    name: 'So far',
    data,
    symbol: 'emptyCircle',
    symbolSize: 9,
    showSymbol: true,
    // NEVER THINNED: on a long axis ECharts hides points at intervals
    // ("auto"), and this one fell on a skipped index -- found in the
    // browser, with the legend naming a point that was not there.
    showAllSymbol: true,
    lineStyle: { width: 0 },
    z: 4,
  }
}

export interface ForecastShape {
  history: Record<string, number>
  running: { start: string; value: number } | null
  points: { start: string; value: number; low: number; high: number }[]
}

/**
 * The recorded totals and where they are heading (R68), on one axis.
 *
 * THE PROJECTION IS DASHED -- the one meaning a dashed line keeps on these
 * charts -- and starts from the last finished period, so it reads as a
 * continuation rather than a second series. THE BAND is the 80% range,
 * a wash of the same colour; the period still running stays a hollow
 * point on the recorded line, beside the projection of where it will
 * finish.
 *
 * ONE COLOUR FOR ALL THREE: they are one quantity, recorded and
 * projected. The legend and the line's style tell them apart, never
 * colour alone.
 */
export function forecastOption(forecast: ForecastShape, period: 'day' | 'week' | 'month'): Record<string, unknown> {
  const finished = Object.keys(forecast.history).sort()
  const ahead = forecast.points.map((point) => point.start)
  const starts = [...new Set([...finished, ...(forecast.running ? [forecast.running.start] : []), ...ahead])].sort()
  const at = new Map(starts.map((start, index) => [start, index]))
  const last = finished.at(-1)
  const blank = (): (number | null)[] => starts.map(() => null)

  const recorded = blank()
  for (const start of finished) recorded[at.get(start)!] = forecast.history[start] ?? null
  const projected = blank()
  const low = blank()
  const spread = blank()
  if (last !== undefined) {
    // ANCHORED on the last finished period, so the dashes leave the line.
    const anchor = forecast.history[last] ?? 0
    projected[at.get(last)!] = anchor
    low[at.get(last)!] = anchor
    spread[at.get(last)!] = 0
  }
  for (const point of forecast.points) {
    const index = at.get(point.start)!
    projected[index] = point.value
    low[index] = point.low
    spread[index] = point.high - point.low
  }
  const runningIndex = forecast.running ? at.get(forecast.running.start) : undefined

  const shown = (value: number | null | undefined) =>
    value === null || value === undefined ? '' : String(Number(value.toFixed(2)))
  return {
    oneColour: true,
    grid: { left: 8, right: 24, top: 32, bottom: 8, containLabel: true },
    // Every series a reader sees, by name -- the hollow point included,
    // since nothing else says what it is.
    legend: { top: 0, data: ['Recorded', ...(runningIndex === undefined ? [] : ['So far']), 'Forecast', '80% range'] },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: starts.map((start) =>
        start === forecast.running?.start ? `${periodLabel(start, period)} (so far)` : periodLabel(start, period),
      ),
      axisLabel: { hideOverlap: true, formatter: (label: string) => label.replace(/^Week of /, '') },
    },
    yAxis: { type: 'value' },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'line' },
      // THE RANGE AS ITS TWO EDGES: the stacked series hold its floor and
      // its width, neither of which a reader asked for.
      formatter: (params: { dataIndex: number; axisValueLabel: string }[]) => {
        const index = params[0]?.dataIndex ?? 0
        const lines = [params[0]?.axisValueLabel ?? '']
        const value = index === runningIndex ? forecast.running!.value : recorded[index]
        if (value !== null && value !== undefined)
          lines.push(index === runningIndex ? `So far: ${shown(value)}` : `Recorded: ${shown(value)}`)
        const point = forecast.points.find((candidate) => candidate.start === starts[index])
        if (point)
          lines.push(`Forecast: ${shown(point.value)}`, `80% range: ${shown(point.low)} to ${shown(point.high)}`)
        return lines.join('<br/>')
      },
    },
    series: [
      {
        type: 'line',
        name: 'Recorded',
        data: recorded,
        lineStyle: { width: 2, cap: 'round', join: 'round' },
        symbol: 'circle',
        showSymbol: starts.length <= 24,
        symbolSize: 8,
        z: 3,
      },
      ...(runningIndex === undefined
        ? []
        : [soFar(starts.map((_, index) => (index === runningIndex ? forecast.running!.value : null)))]),
      {
        type: 'line',
        name: 'Forecast',
        data: projected,
        lineStyle: { width: 2, type: 'dashed' },
        showSymbol: false,
        z: 2,
      },
      // THE BAND, as a stack: an invisible floor at the low edge, and the
      // spread above it washed in.
      {
        type: 'line',
        name: '80% range floor',
        data: low,
        stack: 'band',
        lineStyle: { opacity: 0 },
        showSymbol: false,
        tooltip: { show: false },
        silent: true,
      },
      {
        type: 'line',
        name: '80% range',
        data: spread,
        stack: 'band',
        lineStyle: { opacity: 0 },
        // A wash, not a block -- stronger than a light theme's 10% so it
        // still reads on a dark surface.
        areaStyle: { opacity: 0.2 },
        showSymbol: false,
        silent: true,
      },
    ],
  }
}
