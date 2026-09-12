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
import { BarChart, GraphChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

import { chartTheme } from '../chartColors'

// Registered once, at module load. Registering per render would
// re-register the same modules on every mount for no benefit.
echarts.use([
  BarChart,
  // GraphChart for the ontology graph. Registration is what makes a
  // series type exist: an unregistered one renders NOTHING, with no
  // error -- so a missing entry here looks like a broken option
  // object rather than a missing import.
  GraphChart,
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
  /**
   * A click on something in the chart.
   *
   * `dataType` distinguishes a NODE from an EDGE in a graph series --
   * ECharts sends "node" or "edge", and an edge has no `name`, so a
   * handler reading only the name silently ignores every edge click.
   * That is why clicking a relationship did nothing.
   */
  onSelect?: (name: string, dataType?: string, data?: unknown) => void
  height?: number
  /** For screen readers and for tests, which cannot see a canvas. */
  ariaLabel: string
}

/**
 * Applies Elysium's chart palette to a caller's option object.
 *
 * APPLIED HERE, so no caller chooses colours. Before this, every
 * caller either picked its own or fell through to ECharts' defaults --
 * which meant two charts on one screen could use different palettes,
 * and none of them was checked for colour vision deficiency.
 *
 * A CALLER'S OWN `color` WINS. A chart that genuinely needs specific
 * colours -- a status breakdown where red must mean failed -- says so
 * explicitly, and this must not silently override it. Defaults are
 * supplied; decisions are not overridden.
 *
 * The axis and gridline colours are likewise only filled in where the
 * caller left them unset, and only for axes the caller actually
 * declared: adding an xAxis to a pie chart would make ECharts render
 * an empty grid behind it.
 */
function withTheme(option: Record<string, unknown>): Record<string, unknown> {
  const theme = chartTheme(document.documentElement.classList.contains('bp5-dark'))
  const themed: Record<string, unknown> = { color: theme.categorical, ...option }

  for (const axis of ['xAxis', 'yAxis'] as const) {
    if (option[axis] === undefined) continue
    const declared = option[axis] as Record<string, unknown>
    themed[axis] = {
      ...declared,
      axisLabel: { color: theme.axisLabel, ...(declared.axisLabel as object) },
      splitLine: {
        lineStyle: { color: theme.gridLine },
        ...(declared.splitLine as object),
      },
    }
  }
  return themed
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
    instance.current?.setOption(withTheme(option), true)
  }, [option])

  useEffect(() => {
    const chart = instance.current
    if (chart === null) return
    if (onSelect === undefined) return

    function handleClick(params: { name?: string; dataType?: string; data?: unknown }) {
      // An edge carries its endpoints on `data` rather than a name, so
      // both are forwarded and the caller decides what it needs.
      if (params.name !== undefined || params.dataType === 'edge') {
        onSelect?.(params.name ?? '', params.dataType, params.data)
      }
    }
    chart.on('click', handleClick)
    return () => {
      chart.off('click', handleClick)
    }
  }, [onSelect])

  return <div ref={container} role="img" aria-label={ariaLabel} style={{ height, width: '100%' }} />
}
