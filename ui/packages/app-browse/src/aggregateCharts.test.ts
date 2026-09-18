import { describe, it, expect } from 'vitest'

import {
  MAX_BARS,
  type ChartFilter,
  asConditions,
  selectionFor,
  PIE_MAX_SLICES,
  histogramOption,
  pieOption,
  suitsAPie,
  valueCountsOption,
} from './aggregateCharts'

/**
 * Plain functions, tested directly. The chart they feed draws to a
 * canvas jsdom cannot read, so testing THROUGH a component would test
 * that jsdom returned an empty canvas -- these assert the option
 * object, which is the part with decisions in it.
 */

function manyGroups(count: number): Record<string, number> {
  const results: Record<string, number> = {}
  for (let index = 0; index < count; index += 1) results[`g${index}`] = count - index
  return results
}

describe('value counts', () => {
  it('ranks by count, not by name', () => {
    const option = valueCountsOption({ rare: 1, common: 90, middling: 20 }) as never

    // Reversed for ECharts, which draws a category axis bottom-up, so
    // the LAST entry is the largest and appears at the top.
    const series = (option as { series: { data: { name: string }[] }[] }).series
    const names = (series[0]?.data ?? []).map((d) => d.name)
    expect(names.at(-1)).toBe('common')
  })

  it('folds a long tail into one bucket rather than dropping it', () => {
    // A chart that silently omits the tail misrepresents the total.
    // Someone reading "50 in us-west" out of 200 objects should be
    // able to see that the rest exist.
    const option = valueCountsOption(manyGroups(20)) as unknown as {
      series: { data: { name: string; value: number }[] }[]
    }

    expect(option.series[0]?.data).toHaveLength(MAX_BARS + 1)
    const other = option.series[0]?.data.find((d) => d.name.startsWith('Other'))
    expect(other?.name).toBe('Other (8)')
  })

  it('the other bucket sums what it replaced', () => {
    const results = manyGroups(20)
    const total = Object.values(results).reduce((sum, value) => sum + value, 0)
    const option = valueCountsOption(results) as unknown as {
      series: { data: { value: number }[] }[]
    }

    const charted = (option.series[0]?.data ?? []).reduce((sum, d) => sum + d.value, 0)
    expect(charted).toBe(total)
  })

  it('leaves a short list alone', () => {
    const option = valueCountsOption({ a: 1, b: 2 }) as unknown as {
      series: { data: { name: string }[] }[]
    }

    expect((option.series[0]?.data ?? []).map((d) => d.name).sort()).toEqual(['a', 'b'])
  })

  it('dims what is filtered out rather than hiding it', () => {
    // A filtered-out bar still tells you how much you filtered away.
    // Bars that vanish on click lose the context that made the click
    // sensible.
    const option = valueCountsOption({ west: 10, east: 5 }, { selected: ['west'] }) as unknown as {
      series: { data: { name: string; itemStyle: { opacity: number } }[] }[]
    }

    const byName = Object.fromEntries((option.series[0]?.data ?? []).map((d) => [d.name, d.itemStyle.opacity]))
    expect(byName.west).toBe(1)
    expect(byName.east).toBeLessThan(1)
  })

  it('dims an excluded value even when nothing is selected', () => {
    const option = valueCountsOption({ west: 10, east: 5 }, { excluded: ['east'] }) as unknown as {
      series: { data: { name: string; itemStyle: { opacity: number } }[] }[]
    }

    const byName = Object.fromEntries((option.series[0]?.data ?? []).map((d) => [d.name, d.itemStyle.opacity]))
    expect(byName.west).toBe(1)
    expect(byName.east).toBeLessThan(1)
  })
})

describe('histogram', () => {
  it('keeps the field\u2019s own order rather than ranking', () => {
    // Buckets that mean something in sequence -- dates, amounts -- are
    // unreadable sorted by count.
    const option = histogramOption({ '2026-03': 5, '2026-01': 1, '2026-02': 9 }) as unknown as {
      xAxis: { data: string[] }
    }

    expect(option.xAxis.data).toEqual(['2026-01', '2026-02', '2026-03'])
  })
})

describe('pie', () => {
  it('is offered for a handful of buckets', () => {
    expect(suitsAPie({ a: 1, b: 2, c: 3 })).toBe(true)
  })

  it('is declined past the slice limit', () => {
    // A pie with thirty slices is a colour wheel. Callers ask first
    // and offer a different shape rather than rendering something
    // unreadable.
    expect(suitsAPie(manyGroups(PIE_MAX_SLICES + 1))).toBe(false)
  })

  it('is declined for a single bucket', () => {
    // One slice is a circle. It says nothing a label would not.
    expect(suitsAPie({ only: 42 })).toBe(false)
  })

  it('still folds a tail if asked to draw many', () => {
    const option = pieOption(manyGroups(20)) as unknown as {
      series: { data: { name: string }[] }[]
    }

    expect(option.series[0]?.data ?? []).toHaveLength(PIE_MAX_SLICES + 1)
  })
})

describe('chart selections as conditions', () => {
  it('a kept selection becomes an `in`', () => {
    // No widening was needed for click-to-filter: selecting several
    // values on one chart IS set membership, which the vocabulary
    // already had.
    expect(asConditions([{ field: 'region', values: ['west', 'east'], mode: 'keep' }])).toEqual([
      { field: 'region', operator: 'in', value: ['west', 'east'] },
    ])
  })

  it('an excluded selection becomes a `not_in`', () => {
    // "Everything except these three" is a question people actually
    // ask and a picker cannot express. It is what makes chart
    // filtering more than a fancy dropdown.
    expect(asConditions([{ field: 'region', values: ['east'], mode: 'exclude' }])).toEqual([
      { field: 'region', operator: 'not_in', value: ['east'] },
    ])
  })

  it('fields AND together rather than unioning', () => {
    // Matching how the conditions themselves combine. Two selections
    // on two charts NARROW; a union would widen on every click, which
    // is the opposite of what clicking a bar means.
    const conditions = asConditions([
      { field: 'region', values: ['west'], mode: 'keep' },
      { field: 'status', values: ['open'], mode: 'keep' },
    ])

    expect(conditions).toHaveLength(2)
  })

  it('drops a selection with nothing left in it', () => {
    // `in []` would mean "match nothing" -- an empty filter is no
    // filter, not an impossible one.
    expect(asConditions([{ field: 'region', values: [], mode: 'keep' }])).toEqual([])
  })

  it('reports a field\u2019s own selection for dimming', () => {
    const filters: ChartFilter[] = [{ field: 'region', values: ['west'], mode: 'keep' }]

    expect(selectionFor(filters, 'region')).toEqual({ selected: ['west'], excluded: [] })
    expect(selectionFor(filters, 'status')).toEqual({ selected: [], excluded: [] })
  })

  it('reports an exclusion as excluded, not selected', () => {
    const filters: ChartFilter[] = [{ field: 'region', values: ['east'], mode: 'exclude' }]

    expect(selectionFor(filters, 'region')).toEqual({ selected: [], excluded: ['east'] })
  })
})
