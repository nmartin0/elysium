import { useState } from 'react'
import { query } from '@elysium/shell-api/api'
import type { SubAppProps } from '@elysium/shell-api/types'
import PendingWriteCard, { type PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

interface QueryResponseBody {
  pending_write?: PendingWrite
  answer?: string
  detail?: string
}

// No additional props beyond the shell's own base contract -- see
// SubAppProps's own header comment for the full reasoning on why this
// is a real, shared, exported interface now, not an independently
// redeclared field.
type QueryPanelProps = SubAppProps

// Note on status 499 (client disconnected -- see api/routes.py's
// docstring): deliberately no special handling for it here. By the
// time the server decides the client is gone, this same fetch() call
// has already rejected with a network error on the browser's own side
// -- there's no real scenario where JS code running in a live tab
// ever observes a resolved response carrying status 499. The generic
// catch block below already covers it.
export default function QueryPanel({ onSessionExpired }: QueryPanelProps) {
  const [queryText, setQueryText] = useState('')
  const [answer, setAnswer] = useState<string | null>(null)
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    setAnswer(null)
    setPendingWrite(null)
    setSubmitting(true)

    try {
      // query() itself returns a real, typed Response (not
      // Promise<unknown> like most other api.ts callers -- see that
      // file's own comment on why: /query has four meaningfully
      // different outcomes the caller needs to branch on by status).
      const response = await query(queryText)

      if (response.status === 401) {
        onSessionExpired()
        return
      }

      // response.json() itself is typed `any` by TypeScript's own
      // built-in lib -- asserted to the real, known response body
      // shape here, matching api/routes.py's own documented contract
      // for the query route.
      const body = (await response.json()) as QueryResponseBody

      if (response.status === 202) {
        setPendingWrite(body.pending_write ?? null)
      } else if (response.status === 200) {
        setAnswer(body.answer ?? null)
      } else {
        // 403 (stale permissions were already fine at query time but
        // something else denied it), 409 (permissions changed mid-
        // request), or anything else -- shown exactly as the backend
        // phrased it, not reinterpreted client-side.
        setError(body.detail || `Request failed (${response.status})`)
      }
    } catch {
      setError('Could not reach the server.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="query-panel">
      <form onSubmit={handleSubmit}>
        <textarea
          value={queryText}
          onChange={(event) => setQueryText(event.target.value)}
          placeholder="Ask a question…"
          rows={3}
          required
        />
        <button type="submit" disabled={submitting}>
          {submitting ? 'Thinking…' : 'Ask'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}
      {answer && (
        <div className="answer">
          <p>{answer}</p>
        </div>
      )}
      {pendingWrite && (
        // No persistent view of an object here to refresh once
        // resolved (unlike ObjectDetailPanel.jsx's own ActionForm) --
        // an explicit no-op, not an unset default.
        <PendingWriteCard pendingWrite={pendingWrite} onSessionExpired={onSessionExpired} onResolved={() => {}} />
      )}
    </div>
  )
}
