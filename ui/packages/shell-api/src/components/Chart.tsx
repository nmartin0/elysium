/**
 * Chart.tsx -- the one place that talks to ECharts.
 *
 * Every chart in Elysium renders through here, so no sub-app imports
 * the library or writes its config objects. That matters more than it
 * usually would: ECharts has no first-party React API, so each caller
 * would otherwise hand-roll its own ref, resize handling and dispose
 * -- and a chart that leaks its instance on unmount is the kind of bug
 * that only shows up after a user has opened forty of them.
 *
 * WHY ECHARTS. The charts Elysium needs are histograms, pie charts and
 * eventually Sankey and geo. ECharts covers all of those natively and
 * tree-shakes to what is actually used, which is why the imports below
 * are the individual chart and component modules rather than the
 * bundle. The cost is this file: a config-object API wrapped once,
 * paid here instead of everywhere.
 *
 * DISPOSE IS NOT OPTIONAL. An ECharts instance holds a canvas, a
 * resize listener and its own render loop. React unmounting the div
 * does not free any of that, so the effect's cleanup disposes
 * explicitly -- verified by a test that counts live instances rather
 * than trusting the call is there.
 */

import { useEffect, useRef } from 'react'
import * as echarts from 'echarts/core'
import { BarChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

// Registered once, at module load. Registering per render would
// re-register the same modules on every mount for no benefit.
echarts.use([
  BarChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

export interface ChartProps {
  /** An ECharts option object. Typed as unknown-ish on purpose: this
   *  wrapper does not model ECharts' option schema, which is enormous
   *  and versioned. The chart COMPONENTS above are the typed surface
   *  callers use; this is the escape hatch they build on. */
  option: Record<string, unknown>
  /** Called with the clicked datum's name. Click-to-filter is the
   *  point of these charts, so it is a first-class prop rather than
   *  something each caller wires through ECharts' event API. */
  onSelect?: (name: string) => void
  height?: number
  /** For screen readers and for tests, which cannot see a canvas. */
  ariaLabel: string
}

export default function Chart({ option, onSelect, height = 240, ariaLabel }: ChartProps) {
  const container = useRef<HTMLDivElement | null>(null)
  const instance = useRef<echarts.ECharts | null>(null)

  useEffect(() => {
    if (container.current === null) return
    const chart = echarts.init(container.current)
    instance.current = chart

    // ECharts sizes to its container ONCE at init. Without this a
    // chart in a resizable panel keeps its first width forever.
    const observer = new ResizeObserver(() => chart.resize())
    observer.observe(container.current)

    return () => {
      observer.disconnect()
      chart.dispose()
      instance.current = null
    }
  }, [])

  useEffect(() => {
    instance.current?.setOption(option, true)
  }, [option])

  useEffect(() => {
    const chart = instance.current
    if (chart === null) return
    if (onSelect === undefined) return

    function handleClick(params: { name?: string }) {
      if (params.name !== undefined) onSelect?.(params.name)
    }
    chart.on('click', handleClick)
    return () => {
      chart.off('click', handleClick)
    }
  }, [onSelect])

  return (
    <div
      ref={container}
      role="img"
      aria-label={ariaLabel}
      style={{ height, width: '100%' }}
    />
  )
}
