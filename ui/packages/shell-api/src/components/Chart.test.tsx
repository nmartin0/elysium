import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen } from '@testing-library/react'

import Chart from './Chart'

/**
 * ECharts renders to a canvas, which jsdom cannot draw and a test
 * cannot read. So these assert on the LIBRARY CONTRACT -- was init
 * called, was dispose called, what option was set -- rather than on
 * pixels. Asserting a chart "looks right" here would be asserting that
 * jsdom returned an empty canvas.
 */

const init = vi.fn()
const dispose = vi.fn()
const setOption = vi.fn()
const on = vi.fn()
const off = vi.fn()
const resize = vi.fn()
let clickHandler: ((params: { name?: string; dataType?: string; data?: unknown }) => void) | null = null

vi.mock('echarts/core', async () => {
  return {
    use: vi.fn(),
    init: (...args: unknown[]) => {
      init(...args)
      return {
        setOption,
        dispose,
        resize,
        on: (event: string, handler: (params: { name?: string }) => void) => {
          on(event)
          if (event === 'click') clickHandler = handler
        },
        off,
      }
    },
  }
})
// GraphChart included: registration is what makes a series type
// exist, so a mock missing one turns every test in this file into an
// import error rather than a failure about the thing under test.
vi.mock('echarts/charts', () => ({ BarChart: {}, GraphChart: {}, PieChart: {} }))
vi.mock('echarts/components', () => ({
  GridComponent: {},
  LegendComponent: {},
  TitleComponent: {},
  TooltipComponent: {},
}))
vi.mock('echarts/renderers', () => ({ CanvasRenderer: {} }))

beforeEach(() => {
  vi.clearAllMocks()
  clickHandler = null
  // jsdom has no ResizeObserver.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
})

afterEach(() => {
  vi.unstubAllGlobals()
})

const OPTION = { series: [{ type: 'bar', data: [1, 2] }] }

describe('Chart', () => {
  it('creates one instance and sets the option it was given', () => {
    render(<Chart option={OPTION} ariaLabel="Customers by region" />)

    expect(init).toHaveBeenCalledTimes(1)
    // The caller's own keys survive verbatim. The palette is ADDED
    // around them, which is why this asserts containment rather than
    // equality -- it used to assert equality, and that broke the
    // moment a default was supplied.
    expect(setOption).toHaveBeenCalledWith(expect.objectContaining(OPTION), true)
  })

  describe('the palette', () => {
    it('supplies a colour scale the caller did not ask for', () => {
      // Applied HERE so no caller chooses. Before this, each one either
      // picked its own or fell through to ECharts' defaults, so two
      // charts on one screen could use different palettes and none had
      // been checked for colour vision deficiency.
      render(<Chart option={OPTION} ariaLabel="Customers by region" />)

      const [applied] = setOption.mock.calls[0] as [Record<string, unknown>]
      expect(applied.color).toHaveLength(8)
    })

    it("does NOT override a caller's own colours", () => {
      // THE PROPERTY THAT MATTERS MOST. A status breakdown where red
      // must mean failed says so explicitly, and a wrapper that
      // silently overrode it would be worse than no wrapper.
      const explicit = { ...OPTION, color: ['#ff0000'] }
      render(<Chart option={explicit} ariaLabel="Writes by outcome" />)

      const [applied] = setOption.mock.calls[0] as [Record<string, unknown>]
      expect(applied.color).toEqual(['#ff0000'])
    })

    it('themes axes the caller declared, and invents none', () => {
      // Adding an xAxis to a pie chart makes ECharts render an empty
      // grid behind it, so an axis is themed only where one exists.
      render(<Chart option={{ ...OPTION, xAxis: {} }} ariaLabel="By month" />)

      const [withAxis] = setOption.mock.calls[0] as [Record<string, unknown>]
      expect((withAxis.xAxis as Record<string, unknown>).axisLabel).toBeDefined()
      expect(withAxis.yAxis).toBeUndefined()
    })

    it("leaves a caller's own axis label colour alone", () => {
      const declared = { ...OPTION, xAxis: { axisLabel: { color: '#123456' } } }
      render(<Chart option={declared} ariaLabel="By month" />)

      const [applied] = setOption.mock.calls[0] as [Record<string, unknown>]
      const axis = applied.xAxis as { axisLabel: { color: string } }
      expect(axis.axisLabel.color).toBe('#123456')
    })
  })

  it('disposes the instance on unmount', () => {
    /**
     * NOT optional bookkeeping. An ECharts instance holds a canvas, a
     * resize listener and its own render loop; React removing the div
     * frees none of it. A chart that leaks on unmount is the kind of
     * bug that only appears after someone has opened forty of them.
     */
    const { unmount } = render(<Chart option={OPTION} ariaLabel="Chart" />)

    expect(dispose).not.toHaveBeenCalled()

    unmount()

    expect(dispose).toHaveBeenCalledTimes(1)
  })

  it('replaces the option rather than merging it', () => {
    // setOption's second argument is `notMerge`. Merging would leave a
    // previous series behind when a chart switches from three bars to
    // two -- the stale third would still be drawn.
    render(<Chart option={OPTION} ariaLabel="Chart" />)

    expect(setOption).toHaveBeenCalledWith(expect.anything(), true)
  })

  it('updates when the option changes', () => {
    const { rerender } = render(<Chart option={OPTION} ariaLabel="Chart" />)
    const next = { series: [{ type: 'pie', data: [3] }] }

    rerender(<Chart option={next} ariaLabel="Chart" />)

    // Containment, not equality: the palette is added around the
    // caller's option. Same reason as the first test above.
    expect(setOption).toHaveBeenLastCalledWith(expect.objectContaining(next), true)
    // ...without building a second chart for the same div.
    expect(init).toHaveBeenCalledTimes(1)
  })

  it('reports a clicked datum by name', () => {
    // Click-to-filter is the point of these charts, so selection is a
    // first-class prop rather than each caller wiring ECharts' event
    // API itself.
    const onSelect = vi.fn()
    render(<Chart option={OPTION} onSelect={onSelect} ariaLabel="Chart" />)

    clickHandler?.({ name: 'us-west' })

    // THREE arguments now, not one: dataType and data were added so a
    // graph edge -- which carries no name -- could be reported at all.
    // Existing callers read only the first and are unaffected.
    expect(onSelect).toHaveBeenCalledWith('us-west', undefined, undefined)
  })

  it('ignores a click with no datum behind it', () => {
    // Clicking the chart's blank background fires too, with no name.
    // Treating that as a selection would filter to nothing.
    const onSelect = vi.fn()
    render(<Chart option={OPTION} onSelect={onSelect} ariaLabel="Chart" />)

    clickHandler?.({})

    expect(onSelect).not.toHaveBeenCalled()
  })

  it('does not subscribe to clicks when nobody is listening', () => {
    render(<Chart option={OPTION} ariaLabel="Chart" />)

    expect(on).not.toHaveBeenCalledWith('click')
  })

  it('is labelled, since a canvas says nothing to a screen reader', () => {
    render(<Chart option={OPTION} ariaLabel="Customers by region" />)

    expect(screen.getByRole('img', { name: 'Customers by region' })).toBeInTheDocument()
  })
})

describe('a click on an edge, not just a node', () => {
  it('forwards an edge click, which has no name', () => {
    /**
     * ECharts sends dataType "node" or "edge", and an EDGE HAS NO
     * `name` -- so a handler reading only the name silently ignored
     * every edge click. That is why clicking a relationship did
     * nothing at all.
     */
    const onSelect = vi.fn()
    render(<Chart option={OPTION} onSelect={onSelect} ariaLabel="Chart" />)

    clickHandler?.({ dataType: 'edge', data: { source: 'A', target: 'B' } })

    expect(onSelect).toHaveBeenCalledWith('', 'edge', { source: 'A', target: 'B' })
  })

  it('still forwards a node click', () => {
    // The existing behaviour, asserted alongside so a future change to
    // the edge path cannot quietly break the node one.
    const onSelect = vi.fn()
    render(<Chart option={OPTION} onSelect={onSelect} ariaLabel="Chart" />)

    clickHandler?.({ name: 'Customer', dataType: 'node' })

    expect(onSelect).toHaveBeenCalledWith('Customer', 'node', undefined)
  })
})
