/**
 * What the agent read to produce this answer.
 *
 * The trust argument for putting a model over sensitive data: an
 * answer arrives, and this says what it was built from. Nobody else
 * can offer it -- it needs both an agent AND per-field access logging,
 * and we had both and used neither for this.
 *
 * COLLAPSED BY DEFAULT. The answer is what someone came for; the trace
 * is the follow-up question, and showing forty rows above it would
 * bury the thing they asked for.
 */

import { useState } from 'react'
import { Button, Callout, HTMLTable, Tag } from '@blueprintjs/core'
import { getErrorMessage, getRequestTrace, handleIfSessionExpired } from '@elysium/shell-api/api'

interface TraceEntry {
  object_type: string
  object_id: string | null
  action: string
  rbac_allowed: boolean
  mac_allowed: boolean | null
  timestamp: string
}

export default function AnswerTrace({ requestId, onSessionExpired }: {
  requestId: string
  onSessionExpired: () => void
}) {
  const [entries, setEntries] = useState<TraceEntry[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  /**
   * Fetched on OPEN, not on mount.
   *
   * A trace is read rarely and costs a log scan; fetching one for
   * every answer would make the common case pay for the uncommon one.
   */
  async function toggle() {
    if (open) {
      setOpen(false)
      return
    }
    setOpen(true)
    if (entries !== null) return
    try {
      setEntries(await getRequestTrace(requestId) as TraceEntry[])
    } catch (err: unknown) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    }
  }

  return (
    <div className="answer-trace">
      <Button
        minimal
        small
        icon={open ? 'chevron-down' : 'chevron-right'}
        onClick={toggle}
      >
        How this answer was found
      </Button>

      {open && error && <Callout intent="danger">{error}</Callout>}

      {open && entries !== null && (
        entries.length === 0 ? (
          // A trace can be legitimately empty: an answer needing no
          // object read, or one whose entries fell outside the log
          // scan's window. Saying so beats an empty table.
          <p className="answer-trace__empty">
            No object reads were recorded for this answer.
          </p>
        ) : (
          <HTMLTable compact striped className="answer-trace__table">
            <thead>
              <tr>
                <th>Object type</th>
                <th>Which</th>
                <th>Allowed</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((entry, index) => (
                <tr key={`${entry.timestamp}-${index}`}>
                  <td>{entry.object_type}</td>
                  <td>{entry.object_id ?? '—'}</td>
                  <td>
                    {/* A DENIED read is the interesting row. It says
                        the agent tried to look at something and was
                        refused -- which is the authorization working,
                        and exactly what someone auditing wants to
                        see rather than have hidden. */}
                    {entry.rbac_allowed && entry.mac_allowed !== false ? (
                      <Tag minimal intent="success">yes</Tag>
                    ) : (
                      <Tag minimal intent="warning">refused</Tag>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </HTMLTable>
        )
      )}
    </div>
  )
}
