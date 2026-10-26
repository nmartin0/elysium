/**
 * TimeChart -- values over time, on a time axis, with zoom.
 *
 * The kit's chart for a series: a module gives it lines and it draws
 * them (shell-api/src/timeChart.ts says how, and what each prop means).
 * It fetches nothing, so it serves any source of points -- an
 * aggregate's rows through `seriesFromRows`, a forecast, a feed.
 */

import { Classes } from '@blueprintjs/core'
import { useMemo } from 'react'

import { chartTheme } from '../chartColors'
import { type TimeChartOptions, type TimeSeries, timeChartOption } from '../timeChart'
import Chart from './Chart'

export interface TimeChartProps {
  series: TimeSeries[]
  grain?: TimeChartOptions['grain']
  axisNames?: TimeChartOptions['axisNames']
  height?: number
  /** For screen readers and for tests, which cannot see a canvas. */
  ariaLabel: string
}

export default function TimeChart({ series, grain, axisNames, height = 260, ariaLabel }: TimeChartProps) {
  const option = useMemo(
    () =>
      timeChartOption(series, {
        colors: chartTheme(document.body.classList.contains(Classes.DARK)).categorical,
        grain,
        axisNames,
      }),
    [series, grain, axisNames],
  )
  return <Chart option={option} height={height} ariaLabel={ariaLabel} />
}
