/**
 * Rate, errors and duration, for whoever runs this.
 *
 * THE RED METHOD, the canonical starting point for a request-driven
 * service: a single request-duration record yields all three.
 *
 * SATURATION IS ABSENT AND SAYS SO. The fourth golden signal is a
 * property of the HOST, and the server cannot answer it from inside
 * its own process without guessing at limits it does not know. A
 * screen that quietly omitted it would leave someone believing they
 * were looking at the whole picture.
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MetricsPanel from './MetricsPanel'

vi.mock('@elysium/shell-api/api', () => ({
  getMetrics: vi.fn(),
  getErrorMessage: (error: unknown) => String((error as Error)?.message ?? error),
  handleIfSessionExpired: () => false,
}))

const { getMetrics } = await import('@elysium/shell-api/api')
const mockedGetMetrics = vi.mocked(getMetrics)

const METRICS = {
  window_seconds: 3600,
  requests: 1000,
  rate_per_second: 0.2778,
  error_ratio: 0.023,
  p50_ms: 12.5,
  p99_ms: 840.0,
  slowest_routes: [
    { route: '/api/query', requests: 40, p99_ms: 840.0 },
    { route: '/api/objects/{object_type}/search', requests: 900, p99_ms: 31.0 },
  ],
}

beforeEach(() => {
  mockedGetMetrics.mockReset()
  mockedGetMetrics.mockResolvedValue(METRICS)
})

describe('MetricsPanel', () => {
  it('shows errors as a percentage, not a count', async () => {
    // A count means nothing without a denominator: ten failures is
    // fine in twelve thousand requests and a crisis in twelve.
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('2.3%')).toBeInTheDocument()
  })

  it('shows the tail beside the median, not instead of it', async () => {
    // A median says what a typical request feels like; the tail says
    // what the unlucky one does, and only showing the first hides
    // exactly what people complain about.
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('12.5 ms')).toBeInTheDocument()
    // TWICE, correctly: once as the overall p99 and once as the worst
    // route's. The same number in both places is what it means for one
    // route to dominate the tail.
    expect(screen.getAllByText('840 ms')).toHaveLength(2)
  })

  it('says that saturation is missing rather than omitting it', async () => {
    /** THE ONE THAT MATTERS MOST HERE.
     *
     * Four numbers with no mention of a fifth reads as the whole
     * picture. Naming the gap is the difference between an incomplete
     * dashboard and a misleading one.
     */
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Saturation is not shown/i)).toBeInTheDocument()
    expect(screen.getByText(/property of the host/i)).toBeInTheDocument()
  })

  it('ranks the slowest routes and says how many requests each covers', async () => {
    // A p99 over three requests is not a p99, and a reader needs to
    // know that before acting on it.
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('/api/query')).toBeInTheDocument()
    expect(screen.getByText('40')).toBeInTheDocument()
  })

  it('renders a missing duration as unknown, not as zero', async () => {
    // Zero would read as instantaneous, which is the opposite of "we
    // do not know" and much more alarming to be wrong about.
    mockedGetMetrics.mockResolvedValue({ ...METRICS, p50_ms: null, p99_ms: null })
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    await waitFor(() => expect(screen.getAllByText('—').length).toBeGreaterThan(0))
    expect(screen.queryByText('0 ms')).toBeNull()
  })

  it('says why there is nothing to rank when nothing succeeded', async () => {
    mockedGetMetrics.mockResolvedValue({ ...METRICS, slowest_routes: [] })
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/nothing to rank/i)).toBeInTheDocument()
  })

  it('shows the error rather than an empty screen', async () => {
    // The route is gated on manage:deployment, so a 403 is the
    // expected experience for most users and has to explain itself.
    mockedGetMetrics.mockRejectedValue(new Error('Not permitted'))
    render(<MetricsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('alert')).toHaveTextContent('Not permitted')
  })
})
