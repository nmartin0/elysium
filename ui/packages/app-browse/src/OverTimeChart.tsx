/**
 * OverTimeChart -- how many records fell in each day, week or month of a
 * date field (R68's ground).
 *
 * A DATE IS NOT A CATEGORY. Charted as the others are, a date field drew
 * one bar per distinct date, ranked by how many shared it -- the busiest
 * day first, the order of time lost. Here it is a line over time, from
 * /aggregate's `period`, with empty periods drawn as zero rather than
 * skipped over.
 *
 * THE PERIOD IS THE READER'S: a week by default, the grain most
 * operational questions are asked at; a day or a month one click away.
 *
 * ITS OWN REQUEST, beside the distribution charts', over the same set:
 * the same conditions, frozen set and search text, so the line counts
 * exactly what the table beside it lists.
 *
 * NOT CLICKABLE YET: a point is a range of dates, and filtering the set
 * to a range is a condition this panel does not build.
 *
 * A FORECAST ON REQUEST (R68): the switch asks /forecast for the same
 * set, and the chart extends the line, dashed, with its 80% range. It
 * always says how it was tested and against what; one that did not beat
 * carrying the last period on is not drawn, and the reason is shown
 * instead. Off by default: it is worked out per request, and a chart
 * nobody asked to project should not be.
 */

import { Button, ButtonGroup, Switch } from '@blueprintjs/core'
import {
  aggregateObjects,
  type ForecastResult,
  forecastObjects,
  getErrorMessage,
  handleIfSessionExpired,
  MAX_SCAN_LABEL,
  countsByGroup,
  type TimePeriod,
} from '@elysium/shell-api/api'
import Chart from '@elysium/shell-api/components/Chart'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import Notice from '@elysium/shell-api/components/Notice'
import { useEffect, useState } from 'react'

import { type AggregateResults, forecastOption, overTimeOption } from './aggregateCharts'

const PERIODS: { id: TimePeriod; label: string }[] = [
  { id: 'day', label: 'Day' },
  { id: 'week', label: 'Week' },
  { id: 'month', label: 'Month' },
]

/** How the forecast did when tested, in a sentence: against what, and by
 *  how much. */
function testedSentence(result: ForecastResult, period: TimePeriod): string {
  const backtest = result.backtest
  const number = (value: number | undefined) => (value === undefined ? '?' : String(Number(value.toPrecision(3))))
  const share =
    backtest.share === null || backtest.share === undefined
      ? ''
      : ` (${Math.round(backtest.share * 100)}% of a typical ${period})`
  return (
    `Read as ${backtest.form ?? 'a trend'}. Tested from ${backtest.origins ?? '?'} past points, ` +
    `${backtest.horizon ?? '?'} ${period}s ahead each time, it was off by about ${number(backtest.typical_miss)} a ${period}` +
    `${share}, against ${number(backtest.naive_miss)} for simply carrying the last ${period} on. ` +
    `The shaded range is where 8 in 10 outcomes should fall.`
  )
}

interface OverTimeChartProps {
  objectType: string
  field: string
  label: string
  /** The set's conditions, as the other charts send them. */
  conditions: unknown[]
  frozenSet?: string
  queryText: string
  onSessionExpired: () => void
}

export default function OverTimeChart({
  objectType,
  field,
  label,
  conditions,
  frozenSet,
  queryText,
  onSessionExpired,
}: OverTimeChartProps) {
  const [period, setPeriod] = useState<TimePeriod>('week')
  const [results, setResults] = useState<AggregateResults | null>(null)
  const [truncated, setTruncated] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [projecting, setProjecting] = useState(false)
  const [forecast, setForecast] = useState<ForecastResult | null>(null)
  const [forecastError, setForecastError] = useState<string | null>(null)
  const conditionsKey = JSON.stringify(conditions)

  useEffect(() => {
    setForecast(null)
    setForecastError(null)
    if (!projecting) return
    let cancelled = false
    forecastObjects(objectType, {
      conditions: JSON.parse(conditionsKey) as unknown[],
      ...(frozenSet ? { frozen_set: frozenSet } : {}),
      ...(queryText.trim() ? { q: queryText } : {}),
      aggregate: 'count',
      group_by: field,
      period,
    })
      .then((result) => {
        if (!cancelled) setForecast(result)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setForecastError(getErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projecting, objectType, field, conditionsKey, frozenSet, queryText, period])

  useEffect(() => {
    let cancelled = false
    setResults(null)
    setError(null)
    aggregateObjects(objectType, {
      conditions: JSON.parse(conditionsKey) as unknown[],
      ...(frozenSet ? { frozen_set: frozenSet } : {}),
      ...(queryText.trim() ? { q: queryText } : {}),
      measures: [{ name: 'n', aggregate: 'count' }],
      group_by: field,
      period,
    })
      .then((result) => {
        if (cancelled) return
        setResults(countsByGroup(result, field))
        setTruncated(result.scan_truncated === true)
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
  }, [objectType, field, conditionsKey, frozenSet, queryText, period])

  const periods = results === null ? 0 : Object.keys(results).length

  return (
    <section className="charts-panel__chart charts-panel__chart--over-time" aria-label={`${label} over time`}>
      <header className="charts-panel__over-time-head">
        <h4>{label} over time</h4>
        <Switch
          className="charts-panel__forecast-switch"
          label="Forecast"
          checked={projecting}
          onChange={() => setProjecting((on) => !on)}
        />
        <ButtonGroup aria-label="Count by">
          {PERIODS.map(({ id, label: name }) => (
            <Button key={id} small active={period === id} onClick={() => setPeriod(id)} aria-pressed={period === id}>
              {name}
            </Button>
          ))}
        </ButtonGroup>
      </header>
      {error ? (
        <ErrorState>{error}</ErrorState>
      ) : results === null ? (
        <LoadingState />
      ) : periods < 2 ? (
        <Notice state="neutral">
          {periods === 0
            ? `No record in the current results has a ${label}.`
            : `Every record in the current results falls in the same ${period}; there is no line to draw.`}
        </Notice>
      ) : (
        <>
          {truncated && (
            <Notice state="pending">
              Counted only the first {MAX_SCAN_LABEL} rows, so each {period} is at least what it says rather than
              exactly.
            </Notice>
          )}
          {projecting && forecast?.points.length ? (
            <Chart
              ariaLabel={`${label}: records per ${period}, with a forecast`}
              option={forecastOption(forecast, period)}
            />
          ) : (
            <Chart ariaLabel={`${label}: records per ${period}`} option={overTimeOption(results, period)} />
          )}
          {projecting &&
            (forecastError ? (
              <ErrorState>{forecastError}</ErrorState>
            ) : forecast === null ? (
              <p className="charts-panel__forecast-note">Working out a forecast…</p>
            ) : forecast.refusal ? (
              <Notice state="neutral">No forecast: {forecast.refusal}</Notice>
            ) : (
              <p className="charts-panel__forecast-note">{testedSentence(forecast, period)}</p>
            ))}
        </>
      )}
    </section>
  )
}
