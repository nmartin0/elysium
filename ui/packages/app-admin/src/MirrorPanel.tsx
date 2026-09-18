import { Callout, HTMLTable, Tag } from '@blueprintjs/core'
import { getErrorMessage, getMirrorState, handleIfSessionExpired, type MirrorState } from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useEffect, useState } from 'react'

/**
 * What the mirror holds, table by table.
 *
 * WE BUILT AN INTEGRITY GUARANTEE AND LEFT IT INVISIBLE. A value that
 * cannot be coerced fails the whole table's sync, silver keeps its
 * previous snapshot, and bronze accepts the bad value so it can be
 * diagnosed. That is proven and correct, and the only trace was stderr
 * on whatever ran the sync -- so a user saw data three days stale and
 * an administrator could not find out why from inside the product.
 *
 * It mattered less when the mirror was opt-in. It is now the read
 * path.
 */
export default function MirrorPanel({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [state, setState] = useState<MirrorState | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getMirrorState()
      .then((next) => {
        if (!cancelled) setState(next)
      })
      .catch((caught: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(caught, onSessionExpired)) return
        setError(getErrorMessage(caught))
      })
    return () => {
      cancelled = true
    }
  }, [onSessionExpired])

  if (error) return <ErrorState>{error}</ErrorState>
  if (!state) return <LoadingState label="Reading the mirror…" />

  if (!state.reading_from_mirror) {
    // NOT AN ERROR, and not an empty table either. A deployment
    // reading live has no mirror state, and saying so beats a blank
    // page that looks like a broken sync.
    return (
      <Callout intent="primary" title="This deployment reads live">
        Reads go straight to the configured silos, so there is no mirror to report on. Set{' '}
        <code>read_from_mirror: true</code> to change that.
      </Callout>
    )
  }

  return (
    <>
      {state.problems.length > 0 && (
        <Callout intent="warning" title="Integrity check found problems">
          <ul>
            {state.problems.map((problem) => (
              <li key={problem}>{problem}</li>
            ))}
          </ul>
        </Callout>
      )}

      <HTMLTable compact striped>
        <thead>
          <tr>
            <th>Table</th>
            <th>Last synced</th>
            {/* BOTH LAYERS, SIDE BY SIDE, because their DIVERGENCE is
                the finding. Showing only what Elysium reads would hide
                the case this panel exists for. */}
            <th>Rows served</th>
            <th>Rows fetched</th>
          </tr>
        </thead>
        <tbody>
          {state.tables.map((table) => {
            const identifier = `${table.silo}.${table.table}`
            const behind =
              table.silver_rows !== null && table.bronze_rows !== null && table.bronze_rows !== table.silver_rows
            return (
              <tr key={identifier}>
                <td>{identifier}</td>
                <td>
                  {table.last_synced_at ? (
                    formatTimestamp(table.last_synced_at)
                  ) : (
                    <Tag minimal intent="warning">
                      never
                    </Tag>
                  )}
                </td>
                <td>{table.silver_rows ?? '—'}</td>
                <td>
                  {table.bronze_rows ?? '—'}
                  {behind && (
                    /* THE GAP, NAMED. Bronze took rows that silver
                       refused to interpret, which means the last sync
                       was rejected and what is being served is the
                       snapshot before it. A number alone would leave a
                       reader to spot the difference and guess what it
                       meant. */
                    <Tag minimal intent="warning" style={{ marginInlineStart: '0.5rem' }}>
                      {/* THE DIRECTION SAYS WHICH FAULT IT IS. A first
                          version said "fetched but not served" for
                          both, which is right when bronze has MORE and
                          wrong when it has fewer -- seen on a real
                          deployment serving 67 against 7 fetched,
                          where nothing had been dropped and silver was
                          simply out of date. */}
                      {table.bronze_rows! > table.silver_rows!
                        ? 'fetched but not served — the last sync was refused'
                        : 'serving more than was last fetched — silver is out of date'}
                    </Tag>
                  )}
                </td>
              </tr>
            )
          })}
        </tbody>
      </HTMLTable>

      {state.tables.length === 0 && (
        <Callout intent="primary" title="Nothing synced yet">
          Run <code>python -m scripts.run_sync</code> to copy from the configured silos.
        </Callout>
      )}
    </>
  )
}
