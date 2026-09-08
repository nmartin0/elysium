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
    xAxis: { type: "value" },
    // Reversed because ECharts draws a category axis bottom-up, and a
    // ranked list reads top-down.
    yAxis: { type: "category", data: entries.map(([name]) => name).reverse() },
    tooltip: { trigger: "item" },
    series: [{
      type: "bar",
      data: entries.map(([name, value]) => ({
        name,
        value,
        // Selection is shown by DIMMING the rest rather than hiding
        // it: a filtered-out bar still tells you how much you filtered
        // away, and a chart whose bars vanish on click loses the
        // context that made the click sensible.
        itemStyle: {
          opacity: dimmed(name, selected, excluded) ? 0.3 : 1,
        },
      })).reverse(),
    }],
  }
}

export function histogramOption(results: AggregateResults): Record<string, unknown> {
  // The field's OWN order, not by count -- a histogram over buckets
  // that mean something in sequence (dates, amounts) is unreadable
  // ranked.
  const entries = Object.entries(results).sort(([a], [b]) => a.localeCompare(b))
  return {
    grid: { left: 8, right: 16, top: 8, bottom: 8, containLabel: true },
    xAxis: { type: "category", data: entries.map(([name]) => name) },
    yAxis: { type: "value" },
    tooltip: { trigger: "item" },
    series: [{ type: "bar", data: entries.map(([name, value]) => ({ name, value })) }],
  }
}

export function pieOption(results: AggregateResults): Record<string, unknown> {
  const entries = withOther(sortedEntries(results), PIE_MAX_SLICES)
  return {
    tooltip: { trigger: "item" },
    legend: { type: "scroll", bottom: 0 },
    series: [{
      type: "pie",
      radius: ["40%", "70%"],
      data: entries.map(([name, value]) => ({ name, value })),
    }],
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
  mode: "keep" | "exclude"
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
      operator: filter.mode === "exclude" ? "not_in" : "in",
      value: filter.values,
    }))
}

/** The values selected on one field's chart, for dimming the rest. */
export function selectionFor(filters: ChartFilter[], field: string): {
  selected: string[]
  excluded: string[]
} {
  const filter = filters.find((entry) => entry.field === field)
  if (filter === undefined) return { selected: [], excluded: [] }
  return filter.mode === "exclude"
    ? { selected: [], excluded: filter.values }
    : { selected: filter.values, excluded: [] }
}
