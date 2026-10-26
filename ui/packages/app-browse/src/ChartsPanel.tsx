/**
 * ChartsPanel -- what a result set looks like, rather than what it
 * lists.
 *
 * One chart per field worth bucketing, from /aggregate. This is the
 * "Charts" half of Object Explorer; the table is the other.
 *
 * WHICH FIELDS GET A CHART. The ones the ontology author declared
 * PROMINENT, which is the same metadata the result table defaults its
 * columns to -- an author who said "these are what matter about a
 * Customer" should not have to say it twice. Falling back to every
 * non-hidden data field when none are declared, because a Charts tab
 * showing nothing is worse than one showing too much.
 *
 * Link fields are excluded: counting objects by a relationship has no
 * meaning and /aggregate has no column to group on.
 *
 * ONE REQUEST PER CHART, deliberately, because /aggregate answers
 * about one group_by at a time. They are issued together rather than
 * in sequence -- a Charts tab that painted one chart per round trip
 * would take as many seconds as it has fields.
 */

import { useEffect, useState } from 'react'
import Notice from '@elysium/shell-api/components/Notice'
import Chart from '@elysium/shell-api/components/Chart'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import {
  aggregateObjects,
  getErrorMessage,
  handleIfSessionExpired,
  MAX_SCAN_LABEL,
  countsByGroup,
} from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'

import OverTimeChart from './OverTimeChart'
import {
  type AggregateResults,
  type ChartFilter,
  pieOption,
  conditionsExcluding,
  selectionFor,
  suitsAPie,
  valueCountsOption,
} from './aggregateCharts'

interface ChartsPanelProps {
  objectType: string
  /** The rest of the set's definition -- the filter bar's conditions.
   *  See Facets: without them the charts described a bigger set than
   *  the table beside them. */
  extraConditions?: unknown[]
  /** A frozen set the charts are drawn within. */
  frozenSet?: string
  visibleSchema: VisibleSchema | null
  /** Free-text query, so charts describe the same object set the table
   *  does. */
  queryText: string
  /** The current chart selection, so each chart can dim what is
   *  filtered out rather than hiding it. */
  filters: ChartFilter[]
  onSelect: (field: string, value: string) => void
  onSessionExpired: () => void
}

interface FieldChart {
  field: string
  label: string
  results: AggregateResults
  /** The set was cut off at the scan ceiling before these were
   *  counted, so every value is a floor. Carried per chart rather
   *  than per panel: each field is its own request over its own
   *  condition set (`conditionsExcluding` drops that field's own
   *  filter), so one can truncate while the next does not. */
  truncated: boolean
}

/** The data types a field is charted over time for, not counted by value. */
const TEMPORAL = new Set(['date', 'timestamp', 'timestamptz'])

export function chartableFields(
  objectType: string,
  visibleSchema: VisibleSchema | null,
): { field: string; label: string; overTime: boolean }[] {
  const fields = visibleSchema?.[objectType]?.fields ?? {}
  const usable = Object.entries(fields).filter(([, field]) => field.type !== 'link')
  const prominent = usable.filter(([, field]) => field.visibility === 'prominent')
  const chosen = prominent.length > 0 ? prominent : usable.filter(([, field]) => field.visibility !== 'hidden')
  return chosen.map(([name, field]) => ({
    field: name,
    label: field.display_name ?? name,
    // A DATE IS DRAWN OVER TIME (R68), not counted value by value.
    overTime: TEMPORAL.has(field.data_type ?? ''),
  }))
}

/** Whether a field's distribution says anything.
 *
 * TWO WAYS TO SAY NOTHING, and they are mirrors:
 *
 *   ONE GROUP -- every object shares a value. One bar is not a
 *   distribution.
 *
 *   AS MANY GROUPS AS OBJECTS -- every value is distinct. That is an
 *   identifier, not a category, and a chart of it has one slice per
 *   row.
 *
 * NOT A RATIO OR A THRESHOLD, deliberately. "Drop it if more than 80%
 * of values are unique" would need a number nobody can justify, and
 * would silently hide a real distribution that happened to be sparse.
 * The two exact cases are the ones that are definitely useless.
 */
function isWorthCharting(chart: { results: AggregateResults }): boolean {
  const groups = Object.keys(chart.results).length
  const objects = Object.values(chart.results).reduce(
    (total, count) => total + (typeof count === 'number' ? count : 0),
    0,
  )
  return groups > 1 && groups < objects
}

export default function ChartsPanel({
  objectType,
  visibleSchema,
  queryText,
  filters,
  onSelect,
  onSessionExpired,
  extraConditions = [],
  frozenSet,
}: ChartsPanelProps) {
  const [charts, setCharts] = useState<FieldChart[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // WHICH fields could not be aggregated, named rather than counted. A
  // person deciding whether the picture is complete needs to know
  // WHAT is missing from it -- "one chart failed" does not tell them
  // whether to trust what they are looking at.
  const [failedFields, setFailedFields] = useState<string[]>([])
  // WHICH CHARTS ARE DRAWN FROM A CUT-OFF SET, named for the same
  // reason the failures are. A failed chart is absent, which a reader
  // can see; a TRUNCATED one is present, confident and short -- every
  // bar a floor rather than a count, with nothing on the canvas
  // saying so. That is the worse of the two and was the unreported
  // one.
  const [partialFields, setPartialFields] = useState<string[]>([])

  const chartable = chartableFields(objectType, visibleSchema)
  const fields = chartable.filter((field) => !field.overTime)
  const overTime = chartable.filter((field) => field.overTime)
  // Serialised so the effect depends on the CONTENT of the filter
  // rather than the array's identity, which is new on every render of
  // the parent.
  const filterKey = JSON.stringify(filters)
  // SERIALISED for the same reason as the filters above: the array is new
  // on every parent render, and depending on its identity refetched.
  const extraKey = JSON.stringify(extraConditions)

  useEffect(() => {
    let cancelled = false
    setCharts(null)
    setError(null)
    setFailedFields([])
    setPartialFields([])

    // ALL-SETTLED, NOT ALL. One field failing used to reject the whole
    // batch, so a single unaggregatable column replaced every chart
    // with an error -- five perfectly good distributions thrown away
    // because the sixth could not be computed.
    //
    // WHAT MUST NOT HAPPEN INSTEAD is a quiet partial: showing five
    // charts as though they were all of them is a wrong answer
    // reporting success. So the failures are NAMED below, beside the
    // charts that worked.
    Promise.allSettled(
      fields.map(async ({ field, label }) => {
        const body = await aggregateObjects(objectType, {
          // Every OTHER chart's selection, not this one's -- a chart
          // that filtered itself would drop to a single bar the moment
          // you clicked it.
          conditions: [
            ...conditionsExcluding(JSON.parse(filterKey) as ChartFilter[], field),
            ...(JSON.parse(extraKey) as unknown[]),
          ],
          ...(frozenSet ? { frozen_set: frozenSet } : {}),
          // THE TEXT, which this panel received as a prop "so charts
          // describe the same object set the table does" and never
          // sent. queryText was in the effect's dependencies -- so the
          // charts REFETCHED on every keystroke and drew the same
          // unfiltered set each time.
          ...(queryText.trim() ? { q: queryText } : {}),
          measures: [{ name: 'n', aggregate: 'count' }],
          group_by: field,
        })
        return {
          field,
          label,
          results: countsByGroup(body, field),
          truncated: body.scan_truncated === true,
        }
      }),
    )
      .then((settled) => {
        if (cancelled) return

        // A rejected session must still log the person out, which a
        // settled result would otherwise swallow into a failed-field
        // name.
        const rejected = settled.filter((entry) => entry.status === 'rejected')
        for (const entry of rejected) {
          if (handleIfSessionExpired(entry.reason, onSessionExpired)) return
        }

        const loaded = settled.filter((entry) => entry.status === 'fulfilled').map((entry) => entry.value)
        // EVERYTHING FAILING IS NOT A PARTIAL RESULT, and wants a
        // different message. Naming the fields would say WHAT is
        // missing while losing WHY -- and when nothing worked, the
        // reason is the only useful thing left to say.
        if (loaded.length === 0 && rejected.length > 0) {
          setError(getErrorMessage(rejected[0]?.reason))
          return
        }

        setFailedFields(fields.filter((_, index) => settled[index]?.status === 'rejected').map(({ label }) => label))
        // NAMED FROM THE LOADED CHARTS, not by index into `fields`:
        // only a fulfilled request carries a flag at all, and the two
        // lists diverge the moment one field fails.
        setPartialFields(loaded.filter((chart) => chart.truncated).map(({ label }) => label))
        // A field where every object shares one value tells you
        // nothing -- one bar is not a distribution. Dropped rather
        // than drawn, so the tab shows only charts worth looking at.
        //
        // AND THE MIRROR OF THAT, which was missing: a field where
        // every value is DISTINCT is an identifier, not a category. A
        // pie chart of `name` draws one slice per customer, each
        // exactly one object, and conveys nothing that counting the
        // rows would not.
        //
        // Both failures are the same mistake from opposite ends -- a
        // distribution needs fewer groups than objects and more than
        // one -- so they are tested and refused together.
        setCharts(loaded.filter(isWorthCharting))
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      })

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objectType, filterKey, queryText, extraKey, frozenSet])

  return (
    <>
      {failedFields.length > 0 && (
        // BESIDE THE CHARTS, not instead of them. The five that worked
        // are still worth looking at; what makes them safe to look at
        // is knowing the sixth is missing.
        <ErrorState title="Some charts could not be drawn">{failedFields.join(', ')}</ErrorState>
      )}
      {partialFields.length > 0 && (
        // PENDING, NOT ERROR. Nothing failed -- the numbers are real,
        // they are simply floors, and colouring that as a failure
        // would teach people to ignore the colour that means one.
        //
        // NAMED, like the failures beside it, because "a chart is
        // partial" does not tell a reader WHICH bar they should not
        // quote.
        <Notice state="pending" className="charts-panel__partial">
          Counted only the first {MAX_SCAN_LABEL} rows for {partialFields.join(', ')}, so those bars are at least what
          they say rather than exactly. Narrow the set to chart all of it.
        </Notice>
      )}
      <AsyncPanel error={error} data={charts}>
        {(charts) =>
          // An EMPTY result is not a loading state and not a failure --
          // every field has one distinct value, which is a true answer
          // and needs saying rather than showing an empty box.
          charts.length === 0 && overTime.length === 0 ? (
            <Notice state="neutral">
              No field in this object type has more than one distinct value in the current results, so there is nothing
              to chart.
            </Notice>
          ) : (
            <div className="charts-panel">
              {overTime.map(({ field, label }) => (
                <OverTimeChart
                  key={field}
                  objectType={objectType}
                  field={field}
                  label={label}
                  conditions={[...conditionsExcluding(filters, field), ...extraConditions]}
                  frozenSet={frozenSet}
                  queryText={queryText}
                  onSessionExpired={onSessionExpired}
                />
              ))}
              {charts.map((chart) => (
                <section key={chart.field} className="charts-panel__chart">
                  <h4>{chart.label}</h4>
                  <Chart
                    ariaLabel={`${chart.label} distribution`}
                    onSelect={(value) => onSelect(chart.field, value)}
                    option={
                      suitsAPie(chart.results)
                        ? pieOption(chart.results)
                        : valueCountsOption(chart.results, selectionFor(filters, chart.field))
                    }
                  />
                </section>
              ))}
            </div>
          )
        }
      </AsyncPanel>
    </>
  )
}
