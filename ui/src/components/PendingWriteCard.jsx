import { useState } from 'react'
import { confirmWrite, ApiError } from '../api'

// The client-side half of the two-phase write flow -- /query already
// returned this reference without touching any data; nothing happens
// until the person clicks one of these two buttons, which is exactly
// the point of the whole design (see core/agent/agentic_loop.py's
// docstring for why AgentLoop itself never confirms a write on its
// own).
export default function PendingWriteCard({ pendingWrite, onSessionExpired }) {
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [outcome, setOutcome] = useState(null)

  async function handleDecision(approved) {
    setSubmitting(true)
    setError(null)
    try {
      await confirmWrite(pendingWrite.id, approved)
      setOutcome(approved ? 'Change applied.' : 'Change rejected.')
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        onSessionExpired()
        return
      }
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (outcome) {
    return (
      <div className="pending-write pending-write--resolved">
        <p>{outcome}</p>
      </div>
    )
  }

  return (
    <div className="pending-write">
      <h3>Proposed change</h3>
      <p>{pendingWrite.description}</p>
      <pre>{JSON.stringify(pendingWrite.changes, null, 2)}</pre>
      {error && <p className="error">{error}</p>}
      <div className="pending-write__actions">
        <button onClick={() => handleDecision(true)} disabled={submitting}>
          Approve
        </button>
        <button
          className="secondary"
          onClick={() => handleDecision(false)}
          disabled={submitting}
        >
          Reject
        </button>
      </div>
    </div>
  )
}
