/**
 * What values a field holds, how many of each, and one click to narrow.
 *
 * DEV_UI.md section 5 item 2: "FACETED FILTERS WITH PILLS AND COUNTS,
 * replacing form-style filtering: distributions, filter-to and
 * filter-out, applied filters always visible." It is the fourth of the
 * six patterns section 2 draws out of Palantir's own tools -- Vertex
 * filters a whole graph "with property HISTOGRAMS and 'filter to /
 * filter out'".
 *
 * WHAT WAS ALREADY HERE, which is most of the machinery. The aggregate
 * route computes a distribution with `aggregate: 'count'` and a
 * `group_by`; `ChartFilter` already carries `mode: 'keep' | 'exclude'`,
 * so filter-to and filter-out exist; and `conditionsExcluding` already
 * implements the rule that makes facets correct. The missing piece was
 * that all of it was reachable only by clicking a chart, which means a
 * person had to switch views to narrow a set.
 *
 * A FACET'S COUNTS EXCLUDE ITS OWN FILTER, which is what
 * `conditionsExcluding` is for and the thing naive implementations get
 * wrong. Having filtered Region to us-east, the Region facet must still
 * show us-west and its count -- otherwise the only value you can see is
 * the one you already chose, and the control becomes a dead end rather
 * than a way to move.
 *
 * COUNTS COME FROM THE SAME MEDIATOR AS THE RESULTS, so a value the
 * caller may not read does not appear and is not counted. A facet is a
 * view of the set, and the set is already filtered per caller.
 */

import { useEffect, useState } from 'react'

import { aggregateObjects } from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import StatusTag from '@elysium/shell-api/components/StatusTag'

import { type ChartFilter, conditionsExcluding } from './aggregateCharts'

/** Past this, a distribution is a list of identifiers rather than a
 *  set of categories. Twelve matches the bar-chart ceiling next door,
 *  for the same reason: beyond it the labels crowd each other out. */
const MAX_FACET_VALUES = 12

interface Bucket {
  value: string
  count: number
}

export default function Facets({
  objectType,
  field,
  filters,
  onFilter,
}: {
  objectType: string
  field: string
  filters: ChartFilter[]
  onFilter: (filter: ChartFilter) => void
}) {
  const [buckets, setBuckets] = useState<Bucket[] | null>(null)
  const [failed, setFailed] = useState(false)
  const key = JSON.stringify(filters)

  useEffect(() => {
    let cancelled = false
    // NO setState IN THE EFFECT BODY, which oxlint refuses with
    // "effects should synchronize React with external systems". The
    // reset belonged there to clear a stale failure when the field or
    // filters change; it happens in the success and failure callbacks
    // instead, where it is a response to the fetch rather than a
    // second render triggered by the effect itself.
    aggregateObjects(objectType, {
      conditions: conditionsExcluding(JSON.parse(key) as ChartFilter[], field),
      aggregate: 'count',
      group_by: field,
    })
      .then((rows) => {
        if (cancelled) return
        setFailed(false)
        // AN OBJECT KEYED BY GROUP, not an array of rows -- the shape
        // `AggregateResults` already declares and ChartsPanel already
        // consumes. I assumed rows, the `.map` threw, and every facet
        // rendered "Counts unavailable" while the request itself
        // returned 200. Reading the existing type would have been
        // faster than reading the screenshot.
        // `{ results: AggregateResults }`, which ChartsPanel unwraps
        // the same way. Two wrong guesses at this shape before reading
        // the line next door: first an array of rows, then the bare
        // object. Both rendered without erroring -- one as "Counts
        // unavailable", one as a single row called "results" with a
        // count of NaN -- which is why a screenshot caught what a
        // passing typecheck did not.
        const { results } = rows as { results: Record<string, number> }
        const counts = results
        setBuckets(
          Object.entries(counts)
            .map(([value, count]) => ({ value, count: Number(count) }))
            .sort((a, b) => b.count - a.count),
        )
      })
      .catch(() => {
        // A FACET IS AN AID, NOT THE SEARCH. If the distribution cannot
        // be computed the filter bar below still works, so this reports
        // quietly rather than taking the pane with it.
        if (!cancelled) setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [objectType, field, key])

  if (failed) return <p className="facets__failed">Counts unavailable.</p>
  if (buckets === null || buckets.length === 0) return null

  /**
   * A FACET WITH ONE ROW PER OBJECT IS NOT A FACET.
   *
   * `chartableFields` offers every field a chart could group by, which
   * includes names and email addresses -- and a distribution over those
   * is the result list again, in a narrower column, with every count at
   * 1. It tells a reader nothing and makes the pane longer than the
   * results beside it.
   *
   * The test is the distribution itself rather than a declared
   * cardinality, because the ontology does not say which fields are
   * identifiers and the data answers the question directly. Anything
   * past this many distinct values is a field you search, not one you
   * facet.
   */
  if (buckets.length > MAX_FACET_VALUES) return null

  const active = filters.find((filter) => filter.field === field)

  return (
    <ul className="facets">
      {buckets.map((bucket) => {
        const kept = active?.mode === 'keep' && active.values.includes(bucket.value)
        const excluded = active?.mode === 'exclude' && active.values.includes(bucket.value)
        return (
          <li key={bucket.value} className="facets__row">
            <Action
              className="facets__value"
              text={bucket.value}
              active={kept}
              onClick={() => onFilter({ field, values: [bucket.value], mode: 'keep' })}
            />
            {/* FILTER-OUT IS ITS OWN CONTROL, not a modifier key. A
                shift-click is invisible: nothing on screen says it
                exists, and this is the pane a person is reading to
                learn what they can do. */}
            <Action
              className="facets__exclude"
              icon="small-cross"
              aria-label={`Exclude ${bucket.value}`}
              active={excluded}
              onClick={() => onFilter({ field, values: [bucket.value], mode: 'exclude' })}
            />
            <StatusTag>{bucket.count.toLocaleString()}</StatusTag>
          </li>
        )
      })}
    </ul>
  )
}
