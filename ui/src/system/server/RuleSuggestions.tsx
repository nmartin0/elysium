/**
 * Cleaning suggestions -- values that announce themselves as absences or
 * impossible dates, for a person to accept or dismiss (R31).
 *
 * THE OWNER'S SHAPE (14 Oct): the YAML stays the only source of rules.
 * Accepting a suggestion records the judgement and shows the exact lines
 * to add to ontology_schema.yaml; it does not write them. Dismissing one
 * is remembered, so an "N/A" somebody has already judged to be a real
 * sentence is never raised again. Once the schema declares a rule, the
 * next scan marks its suggestion "declared".
 *
 * ONLY FIELDS YOU MAY READ are listed. A suggestion carries values from
 * its field, and managing the deployment is not clearance to read it.
 */

import { useCallback, useState } from 'react'
import { Button } from '@blueprintjs/core'
import StatusTag, { type TagState } from '@elysium/shell-api/components/StatusTag'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import {
  decideRuleSuggestion,
  getErrorMessage,
  getRuleSuggestions,
  handleIfSessionExpired,
  scanRuleSuggestions,
  type RuleSuggestion,
} from '@elysium/shell-api/api'
import { formatTimestamp } from '@elysium/shell-api/format'
import { useFetchOnce } from '@elysium/shell-api/useFetchOnce'
import DataTable from '@elysium/shell-api/components/DataTable'

const STATE_TAG: Record<RuleSuggestion['state'], TagState> = {
  pending: 'pending',
  accepted: 'granted',
  dismissed: 'neutral',
  declared: 'active',
}

/** What the value column says: the value for an absence; the dates seen
 *  for a range, whose rule is per field. */
function shown(item: RuleSuggestion): string {
  return item.kind === 'absence' ? item.value : item.examples.join(', ')
}

export default function RuleSuggestions({ onSessionExpired }: { onSessionExpired: () => void }) {
  // THE FIRST LOAD THROUGH useFetchOnce, like every other Admin panel;
  // after a scan or a decision the list is read again into `latest`,
  // which wins over it.
  const { data, error: loadError } = useFetchOnce<RuleSuggestion[]>(getRuleSuggestions, onSessionExpired)
  const [latest, setLatest] = useState<RuleSuggestion[] | null>(null)
  const items = latest ?? data
  const [error, setError] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanned, setScanned] = useState<string | null>(null)

  const fail = useCallback(
    (err: unknown) => {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    },
    [onSessionExpired],
  )

  async function load() {
    try {
      setLatest(await getRuleSuggestions())
    } catch (err: unknown) {
      fail(err)
    }
  }

  async function scan() {
    setScanning(true)
    setError(null)
    try {
      const outcome = await scanRuleSuggestions()
      setScanned(
        `${outcome.new ?? 0} new, ${outcome.updated ?? 0} still open, ${outcome.declared ?? 0} already declared, ` +
          `${outcome.kept_dismissed ?? 0} dismissed earlier and not raised again`,
      )
      await load()
    } catch (err: unknown) {
      fail(err)
    } finally {
      setScanning(false)
    }
  }

  async function decide(item: RuleSuggestion, decision: 'accepted' | 'dismissed') {
    setError(null)
    try {
      await decideRuleSuggestion(item.id, decision)
      await load()
    } catch (err: unknown) {
      fail(err)
    }
  }

  return (
    <section className="rule-suggestions">
      <p className="rule-suggestions__explainer">
        Values in the raw copy of your sources that look like a missing value written as data, or a date no business
        has. Accept one to get the lines to add to <code>ontology_schema.yaml</code>; dismiss one and it is not raised
        again. Nothing here changes data or configuration.
      </p>
      <Button icon="search" onClick={scan} loading={scanning}>
        Scan bronze now
      </Button>
      {scanned && <p className="rule-suggestions__outcome">Scanned: {scanned}.</p>}
      {(error ?? loadError) && <ErrorState>{error ?? loadError}</ErrorState>}

      {items === null ? (
        loadError ? null : (
          <LoadingState />
        )
      ) : items.length === 0 ? (
        <p className="rule-suggestions__empty">No suggestions. Scan to look.</p>
      ) : (
        <DataTable className="rule-suggestions__table">
          <thead>
            <tr>
              <th>Field</th>
              <th>Value</th>
              <th>Seen</th>
              <th>Why</th>
              <th>State</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.id}>
                <td>
                  {item.object_type}.{item.field}
                </td>
                <td>
                  <code>{shown(item)}</code>
                </td>
                <td>{item.seen}</td>
                <td>{item.why}</td>
                <td title={item.decided_at ? `${item.decided_by} · ${formatTimestamp(item.decided_at)}` : undefined}>
                  <StatusTag state={STATE_TAG[item.state]}>{item.state}</StatusTag>
                </td>
                <td className="rule-suggestions__actions">
                  {item.state === 'pending' && (
                    <>
                      <Button small intent="primary" onClick={() => decide(item, 'accepted')}>
                        Accept
                      </Button>
                      <Button small minimal onClick={() => decide(item, 'dismissed')}>
                        Dismiss
                      </Button>
                    </>
                  )}
                  {item.state === 'accepted' && item.yaml && (
                    <pre className="rule-suggestions__yaml" aria-label={`Lines to add for ${item.field}`}>
                      {item.yaml}
                    </pre>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </DataTable>
      )}
    </section>
  )
}
