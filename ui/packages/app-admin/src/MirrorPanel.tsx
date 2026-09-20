import React from 'react'
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

    function load() {
      getMirrorState()
        .then((next) => {
          if (!cancelled) setState(next)
        })
        .catch((caught: unknown) => {
          if (cancelled) return
          if (handleIfSessionExpired(caught, onSessionExpired)) return
          setError(getErrorMessage(caught))
        })
    }

    load()
    // REFRESHED WHILE THE PAGE IS OPEN, because an administrator
    // watching this screen during an incident should see it change
    // rather than wonder whether to reload.
    //
    // THIRTY SECONDS, and the cost is why it is affordable: the whole
    // endpoint takes about 9ms per table, since row counts come from
    // Iceberg's own metadata rather than from scanning, and pyiceberg
    // caches loaded tables within a catalog.
    //
    // THIS DOES NOT SOLVE THE REAL PROBLEM, and should not be mistaken
    // for solving it. An idle administrator is the EASY case; the hard
    // one is nobody looking at all, at three in the morning. That
    // needs notification, which is recorded in
    // TRIGGERS_AND_PLUGINS.md. A dashboard is for investigating a
    // problem you know about.
    const timer = setInterval(load, 30_000)
    return () => {
      cancelled = true
      clearInterval(timer)
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
      {/* WHY IT WAS REFUSED, above the table, because it is the thing
          somebody opened this screen to find out. The full detail
          rather than a category: a reader who sees a refusal wants the
          column and the offending value, which is exactly what the
          drift report already contains and what stderr was keeping to
          itself. */}
      {state.tables
        .filter((each) => each.last_attempt_outcome === 'refused')
        .map((each) => (
          <Callout
            key={`${each.silo}.${each.table}`}
            intent="warning"
            title={`Last sync of ${each.silo}.${each.table} was refused`}
          >
            <pre className="mirror__refusal">{each.last_attempt_detail}</pre>
            Elysium is still serving the snapshot from before it.
          </Callout>
        ))}

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
            {/* LAST CHANGED, NOT LAST ATTEMPTED, and the header has
                to say which. The timestamp comes from the newest
                Iceberg snapshot, and a sync finding the source
                unchanged writes NO snapshot -- correctly, since
                rewriting identical data costs real bytes for no
                gain.

                So a table synced successfully two minutes ago can
                show a date from last week. That is TRUE, and it
                reads as a failure under a header saying "last
                synced". Seen immediately on a real deployment. */}
            <th>Data last changed</th>
            {/* BOTH LAYERS, SIDE BY SIDE, because their DIVERGENCE is
                the finding. Showing only what Elysium reads would hide
                the case this panel exists for. */}
            {/* LAST ATTEMPT, beside last CHANGE, because they are
                different facts and the gap between them is the
                whole point: a table refusing every sync since
                Tuesday looks identical to one whose source has not
                changed since Tuesday, from snapshots alone. */}
            <th>Last attempt</th>
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
              <React.Fragment key={identifier}>
                <tr>
                  <td>{identifier}</td>
                  <td>
                    {table.last_synced_at ? (
                      formatTimestamp(table.last_synced_at)
                    ) : (
                      <Tag minimal intent="warning">
                        never synced
                      </Tag>
                    )}
                  </td>
                  <td>
                    {table.last_attempt_outcome === 'refused' ? (
                      <Tag intent="warning" minimal>
                        refused{table.last_attempt_at ? ` ${formatTimestamp(table.last_attempt_at)}` : ''}
                      </Tag>
                    ) : table.last_attempt_at ? (
                      formatTimestamp(table.last_attempt_at)
                    ) : (
                      /* NOTHING RECORDED is not a failure. An
                         existing deployment has no attempts until
                         its next sync, and saying "refused" or
                         "never" there would both be wrong. */
                      <span className="bp6-text-muted">not recorded</span>
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
                {(table.snapshots ?? []).length > 0 && (
                  <tr>
                    {/* SPANNING THE ROW, because a history is about
                        the table above it rather than a column of
                        its own. COLLAPSED by default: an admin
                        opening this panel wants the health of every
                        table, not the history of one. */}
                    <td colSpan={5} className="mirror__history">
                      <details>
                        <summary>
                          {(table.snapshots ?? []).length} recent change
                          {(table.snapshots ?? []).length === 1 ? '' : 's'}
                        </summary>
                        <ul>
                          {(table.snapshots ?? []).map((snapshot) => (
                            <li key={snapshot.at}>
                              {formatTimestamp(snapshot.at)}
                              {' — '}
                              {snapshot.operation}
                              {snapshot.rows !== null ? `, ${snapshot.rows} rows` : ''}
                              {snapshot.current ? ' (serving now)' : ''}
                            </li>
                          ))}
                        </ul>
                      </details>
                    </td>
                  </tr>
                )}
              </React.Fragment>
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
