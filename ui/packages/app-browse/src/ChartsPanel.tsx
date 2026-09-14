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
import { Callout } from '@blueprintjs/core'
import Chart from '@elysium/shell-api/components/Chart'
import AsyncPanel from '@elysium/shell-api/components/AsyncPanel'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { aggregateObjects, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'

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
}

export function chartableFields(
  objectType: string,
  visibleSchema: VisibleSchema | null,
): { field: string; label: string }[] {
  const fields = visibleSchema?.[objectType]?.fields ?? {}
  const usable = Object.entries(fields).filter(([, field]) => field.type !== 'link')
  const prominent = usable.filter(([, field]) => field.visibility === 'prominent')
  const chosen = prominent.length > 0 ? prominent : usable.filter(([, field]) => field.visibility !== 'hidden')
  return chosen.map(([name, field]) => ({ field: name, label: field.display_name ?? name }))
}

export default function ChartsPanel({
  objectType,
  visibleSchema,
  queryText,
  filters,
  onSelect,
  onSessionExpired,
}: ChartsPanelProps) {
  const [charts, setCharts] = useState<FieldChart[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  // WHICH fields could not be aggregated, named rather than counted. A
  // person deciding whether the picture is complete needs to know
  // WHAT is missing from it -- "one chart failed" does not tell them
  // whether to trust what they are looking at.
  const [failedFields, setFailedFields] = useState<string[]>([])

  const fields = chartableFields(objectType, visibleSchema)
  // Serialised so the effect depends on the CONTENT of the filter
  // rather than the array's identity, which is new on every render of
  // the parent.
  const filterKey = JSON.stringify(filters)

  useEffect(() => {
    let cancelled = false
    setCharts(null)
    setError(null)
    setFailedFields([])

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
        const body = (await aggregateObjects(objectType, {
          // Every OTHER chart's selection, not this one's -- a chart
          // that filtered itself would drop to a single bar the moment
          // you clicked it.
          conditions: conditionsExcluding(JSON.parse(filterKey) as ChartFilter[], field),
          aggregate: 'count',
          group_by: field,
        })) as { results: AggregateResults }
        return { field, label, results: body.results }
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
        // A field where every object shares one value tells you
        // nothing -- one bar is not a distribution. Dropped rather
        // than drawn, so the tab shows only charts worth looking at.
        setCharts(loaded.filter((chart) => Object.keys(chart.results).length > 1))
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
  }, [objectType, filterKey, queryText])

  return (
    <>
      {failedFields.length > 0 && (
        // BESIDE THE CHARTS, not instead of them. The five that worked
        // are still worth looking at; what makes them safe to look at
        // is knowing the sixth is missing.
        <ErrorState title="Some charts could not be drawn">{failedFields.join(', ')}</ErrorState>
      )}
      <AsyncPanel error={error} data={charts}>
        {(charts) =>
          // An EMPTY result is not a loading state and not a failure --
          // every field has one distinct value, which is a true answer
          // and needs saying rather than showing an empty box.
          charts.length === 0 ? (
            <Callout intent="none">
              No field in this object type has more than one distinct value in the current results, so there is nothing
              to chart.
            </Callout>
          ) : (
            <div className="charts-panel">
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
