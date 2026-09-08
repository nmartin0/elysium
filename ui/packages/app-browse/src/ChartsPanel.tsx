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
import { Callout, Spinner } from '@blueprintjs/core'
import Chart from '@elysium/shell-api/components/Chart'
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
  const chosen = prominent.length > 0
    ? prominent
    : usable.filter(([, field]) => field.visibility !== 'hidden')
  return chosen.map(([name, field]) => ({ field: name, label: field.display_name ?? name }))
}

export default function ChartsPanel({
  objectType, visibleSchema, queryText, filters, onSelect, onSessionExpired,
}: ChartsPanelProps) {
  const [charts, setCharts] = useState<FieldChart[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const fields = chartableFields(objectType, visibleSchema)
  // Serialised so the effect depends on the CONTENT of the filter
  // rather than the array's identity, which is new on every render of
  // the parent.
  const filterKey = JSON.stringify(filters)

  useEffect(() => {
    let cancelled = false
    setCharts(null)
    setError(null)

    Promise.all(
      fields.map(async ({ field, label }) => {
        const body = await aggregateObjects(objectType, {
          // Every OTHER chart's selection, not this one's -- a chart
          // that filtered itself would drop to a single bar the moment
          // you clicked it.
          conditions: conditionsExcluding(JSON.parse(filterKey) as ChartFilter[], field),
          aggregate: 'count',
          group_by: field,
        }) as { results: AggregateResults }
        return { field, label, results: body.results }
      }),
    )
      .then((loaded) => {
        if (cancelled) return
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

  if (error) return <Callout intent="danger">{error}</Callout>
  if (charts === null) return <Spinner />
  if (charts.length === 0) {
    return (
      <Callout intent="none">
        No field in this object type has more than one distinct value in the
        current results, so there is nothing to chart.
      </Callout>
    )
  }

  return (
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
