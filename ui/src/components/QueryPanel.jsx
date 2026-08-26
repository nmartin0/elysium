import { useState } from 'react'
import { query } from '../api'
import PendingWriteCard from './PendingWriteCard'

// Note on status 499 (client disconnected -- see api/routes.py's
// docstring): deliberately no special handling for it here. By the
// time the server decides the client is gone, this same fetch() call
// has already rejected with a network error on the browser's own side
// -- there's no real scenario where JS code running in a live tab
// ever observes a resolved response carrying status 499. The generic
// catch block below already covers it.
export default function QueryPanel({ onSessionExpired }) {
  const [queryText, setQueryText] = useState('')
  const [answer, setAnswer] = useState(null)
  const [pendingWrite, setPendingWrite] = useState(null)
  const [error, setError] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError(null)
    setAnswer(null)
    setPendingWrite(null)
    setSubmitting(true)

    try {
      const response = await query(queryText)

      if (response.status === 401) {
        onSessionExpired()
        return
      }

      const body = await response.json()

      if (response.status === 202) {
        setPendingWrite(body.pending_write)
      } else if (response.status === 200) {
        setAnswer(body.answer)
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
        <PendingWriteCard pendingWrite={pendingWrite} onSessionExpired={onSessionExpired} />
      )}
    </div>
  )
}
