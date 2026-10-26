import { render } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

const chart = vi.fn()
vi.mock('./Chart', () => ({
  default: (props: Record<string, unknown>) => {
    chart(props)
    return <div role="img" aria-label={props.ariaLabel as string} />
  },
}))

const { default: TimeChart } = await import('./TimeChart')

const SERIES = [{ name: 'Orders', points: [{ at: '2026-05-04', value: 5 }] }]

describe('TimeChart', () => {
  it('draws the series on a time axis, labelled for those who cannot see it', () => {
    const { getByRole } = render(<TimeChart series={SERIES} ariaLabel="Orders per week" />)

    expect(getByRole('img')).toHaveAttribute('aria-label', 'Orders per week')
    const { option } = chart.mock.calls[0]![0] as { option: { xAxis: { type: string } } }
    expect(option.xAxis.type).toBe('time')
  })

  it('has room for the slider under the plot', () => {
    render(<TimeChart series={SERIES} ariaLabel="x" />)

    expect((chart.mock.calls.at(-1)![0] as { height: number }).height).toBeGreaterThanOrEqual(260)
  })

  it('does not rebuild its option when it re-renders with the same series', () => {
    const { rerender } = render(<TimeChart series={SERIES} ariaLabel="x" />)
    const first = (chart.mock.calls.at(-1)![0] as { option: unknown }).option
    rerender(<TimeChart series={SERIES} ariaLabel="x" />)

    expect((chart.mock.calls.at(-1)![0] as { option: unknown }).option).toBe(first)
  })

  it('redraws when the series change', () => {
    const { rerender } = render(<TimeChart series={SERIES} ariaLabel="x" />)
    const first = (chart.mock.calls.at(-1)![0] as { option: unknown }).option
    rerender(<TimeChart series={[{ name: 'Revenue', points: SERIES[0]!.points }]} ariaLabel="x" />)

    expect((chart.mock.calls.at(-1)![0] as { option: unknown }).option).not.toBe(first)
  })
})
