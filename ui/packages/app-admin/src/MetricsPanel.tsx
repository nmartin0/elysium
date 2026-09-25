/**
 * Metrics -- rate, errors and duration, for whoever runs this.
 *
 * THE RED METHOD, which is the canonical starting point for a
 * request-driven service: a single request-duration record yields all
 * three. Rate is how many requests fell in the window, duration is
 * their distribution, errors are the share whose status said so.
 *
 * SATURATION IS ABSENT AND SAYS SO. The fourth golden signal is a
 * property of the HOST -- CPU, memory, queue depth -- and the server
 * cannot answer it from inside its own process without guessing at
 * limits it does not know. A screen that quietly omitted it would
 * leave someone believing they were looking at the whole picture; one
 * that invented a number would be worse.
 *
 * ERRORS AS A PERCENTAGE, because a count means nothing without a
 * denominator -- ten failures is fine in twelve thousand requests and
 * a crisis in twelve.
 *
 * p99 BESIDE p50, not instead of it. A median says what a typical
 * request feels like; the tail says what the unlucky one does, and a
 * screen showing only the first would hide exactly what people
 * complain about.
 */

import { Callout, HTMLTable } from '@blueprintjs/core'
import { getErrorMessage, getMetrics, handleIfSessionExpired } from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { useEffect, useRef, useState } from 'react'

interface SlowRoute {
  route: string
  requests: number
  p99_ms: number | null
}

interface Metrics {
  window_seconds: number
  requests: number
  rate_per_second: number
  error_ratio: number
  p50_ms: number | null
  p99_ms: number | null
  slowest_routes: SlowRoute[]
}

interface MetricsPanelProps {
  onSessionExpired: () => void
}

/** A duration, or an honest admission that there isn't one.
 *
 * NULL IS NOT ZERO. A window in which nothing succeeded has no
 * latency, and "0 ms" would read as instantaneous -- the opposite of
 * "we do not know", and much more alarming to be wrong about. */
function duration(ms: number | null): string {
  return ms === null ? '—' : `${ms} ms`
}

export default function MetricsPanel({ onSessionExpired }: MetricsPanelProps) {
  const [metrics, setMetrics] = useState<Metrics | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The session callback through a ref, so this effect has NO
  // dependencies. App.tsx declares handleSessionExpired as a plain
  // function inside the component, so it is a new identity on every
  // render -- and this effect listed it, so every parent render tore
  // the effect down and rebuilt it. The linter never flagged these
  // two; the structural test in useLatest.test.tsx did.
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  useEffect(() => {
    void (getMetrics() as Promise<Metrics>).then(setMetrics).catch((err: unknown) => {
      if (handleIfSessionExpired(err, latestSessionExpired.current)) return
      setError(getErrorMessage(err))
    })
  }, [])

  if (error !== null) return <ErrorState>{error}</ErrorState>
  if (metrics === null) return <LoadingState />

  const windowMinutes = Math.round(metrics.window_seconds / 60)

  return (
    <div className="metrics-panel">
      <p className="metrics-panel__window">
        The last {windowMinutes} minutes. Counters reset when the deployment's data directory is cleared, not when the
        server restarts.
      </p>

      <dl className="metrics-panel__figures">
        <div>
          <dt>Requests</dt>
          <dd>{metrics.requests}</dd>
        </div>
        <div>
          <dt>Rate</dt>
          <dd>{metrics.rate_per_second}/s</dd>
        </div>
        <div>
          <dt>Errors</dt>
          {/* A PERCENTAGE, because a count means nothing without a
              denominator. */}
          <dd>{(metrics.error_ratio * 100).toFixed(1)}%</dd>
        </div>
        <div>
          <dt>Median</dt>
          <dd>{duration(metrics.p50_ms)}</dd>
        </div>
        <div>
          <dt>p99</dt>
          <dd>{duration(metrics.p99_ms)}</dd>
        </div>
      </dl>

      {/* SAID OUT LOUD RATHER THAN OMITTED. Someone reading four
          numbers and seeing no mention of the fifth would reasonably
          conclude this was the whole picture. */}
      <Callout intent="none" title="Saturation is not shown">
        The fourth signal — how close the machine is to its limits — is a property of the host, not of this process.
        Elysium cannot measure it without guessing at limits it does not know, so whatever watches the machine should
        answer it.
      </Callout>

      <h3>Slowest routes</h3>
      {metrics.slowest_routes.length === 0 ? (
        <p className="metrics-panel__empty">No successful requests in this window, so there is nothing to rank.</p>
      ) : (
        <HTMLTable className="metrics-table" striped>
          <thead>
            <tr>
              <th>Route</th>
              {/* THE COUNT BESIDE THE FIGURE, because a p99 over three
                  requests is not a p99 and a reader needs to know that
                  before acting on it. */}
              <th>Requests</th>
              <th>p99</th>
            </tr>
          </thead>
          <tbody>
            {metrics.slowest_routes.map((route) => (
              <tr key={route.route}>
                <td>{route.route}</td>
                <td>{route.requests}</td>
                <td>{duration(route.p99_ms)}</td>
              </tr>
            ))}
          </tbody>
        </HTMLTable>
      )}
    </div>
  )
}
