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

import { aggregateObjects, MAX_SCAN_LABEL, type AggregateResult } from '@elysium/shell-api/api'
import Action from '@elysium/shell-api/components/Action'
import StatusTag from '@elysium/shell-api/components/StatusTag'

import { type ChartFilter, conditionsExcluding } from './aggregateCharts'

/** Past this, a distribution is a list of identifiers rather than a
 *  set of categories. Twelve matches the bar-chart ceiling next door,
 *  for the same reason: beyond it the labels crowd each other out. */
const MAX_FACET_VALUES = 12

/** Past this fraction of distinct values to objects, a field names
 *  things rather than grouping them. Two thirds leaves room for a
 *  genuinely sparse category on a small set without admitting a
 *  column of identifiers. */
const IDENTIFIER_RATIO = 0.66

interface Bucket {
  value: string
  count: number
}

export default function Facets({
  objectType,
  field,
  label,
  filters,
  onFilter,
}: {
  objectType: string
  field: string
  /** The field's display name. Rendered INSIDE the component so a
   *  facet suppressed for high cardinality takes its heading with it --
   *  a heading above nothing is the worst of both. */
  label: string
  filters: ChartFilter[]
  onFilter: (filter: ChartFilter) => void
}) {
  const [buckets, setBuckets] = useState<Bucket[] | null>(null)
  const [failed, setFailed] = useState(false)
  // THE DISTRIBUTION WAS CUT OFF BEFORE IT WAS COUNTED, which makes
  // every count below a FLOOR. Per facet rather than per panel,
  // because each facet is its own request over its own condition set:
  // `conditionsExcluding` deliberately drops this field's own filter,
  // so a facet aggregates a BROADER set than the table beside it and
  // can hit the ceiling on a page where the table did not. That is
  // the dangerous case -- a complete-looking table with short counts
  // next to it -- and a panel-wide flag taken from the search would
  // have missed exactly it.
  const [truncated, setTruncated] = useState(false)
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
        const { results, scan_truncated } = rows as AggregateResult
        setTruncated(scan_truncated === true)
        const counts = results as Record<string, number>
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

  /**
   * WHETHER THIS FACET HAS ANYTHING WORTH SHOWING, decided once and
   * before any return, because a hook cannot follow a conditional one.
   *
   * Two rules, and the second is the one a count alone misses. A field
   * past MAX_FACET_VALUES distinct values is a list, not a set of
   * categories. And a field whose distinct values approach the number
   * of objects IDENTIFIES them rather than grouping them -- four
   * regions among a thousand customers is a facet; four names among
   * four customers is the result list again. Both have four buckets,
   * which is why the ceiling alone let NAME and EMAIL through and a
   * rendered pane showed them with every count at 1.
   *
   * BOTH RULES ARE DECIDED ON WHATEVER CAME BACK, truncated or not,
   * and that is a judgement rather than an oversight. A cut-off
   * distribution could hold more values past the ceiling than
   * MAX_FACET_VALUES admits, so the decision is made on partial
   * evidence -- but suppressing a facet BECAUSE it was truncated
   * would remove the one control that could narrow the set below the
   * ceiling, which is precisely what the person needs. So it is shown
   * and labelled instead. Guessing at the unseen tail would be
   * inventing a number; saying the counts are floors is not.
   */
  const total = (buckets ?? []).reduce((sum, bucket) => sum + bucket.count, 0)
  const visible =
    !failed &&
    buckets !== null &&
    buckets.length > 0 &&
    buckets.length <= MAX_FACET_VALUES &&
    !(total > 0 && buckets.length / total > IDENTIFIER_RATIO)

  if (failed) return <p className="facets__failed">Counts unavailable.</p>
  if (!visible) return null

  const active = filters.find((filter) => filter.field === field)

  return (
    <>
      <p className="facets__field">{label}</p>
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
      {truncated && (
        /* AT LEAST, NOT EXACTLY. "We stopped counting", never "there
           are more for you" -- past the ceiling the rows might all
           have been outside this caller's boundary anyway, so the
           only honest claim is about what was read.

           A LINE RATHER THAN A Notice, and the pane's own comment
           settles why: a Callout in a filter sidebar is an
           interruption, and this is continuous reading beside a
           control the person is already using.

           AND ONE LINE RATHER THAN THREE. This appears once per
           truncated facet, and in a sidebar four repetitions of a
           three-line paragraph drown the counts they annotate --
           seen in a browser before it was shortened. "Narrow the
           set" is advice the search's own notice gives once, under
           the results, where it only has to be read once. */
        <p className="facets__partial">At least — counting stopped at {MAX_SCAN_LABEL} rows.</p>
      )}
    </>
  )
}
