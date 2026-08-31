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
      {/* Minimal, plain rendering -- loops over sub_writes so this
          reads correctly regardless of how many objects an action
          touches, matching the backend's own uniform response shape
          (see api/routes.py's own docstring). A real, polished
          multi-object confirmation UI (separate labeled sections per
          object, etc.) is deliberately deferred until a real multi-
          object action exists to design it against -- see this
          file's own AI-notes at the bottom. */}
      {pendingWrite.sub_writes.map((subWrite, i) => (
        <div key={i} className="pending-write__sub-write">
          <p className="pending-write__sub-write-label">
            {subWrite.object_type} {subWrite.object_id}
          </p>
          <pre>{JSON.stringify(subWrite.changes, null, 2)}</pre>
        </div>
      ))}
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

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// DEFERRED (known, intentional, not yet built):
// - This rendering is deliberately MINIMAL, not the real design: each
//   sub_write just gets a plain "<type> <id>" label plus its raw JSON
//   changes dump. A real multi-object confirmation UI (visually
//   distinct sections per object, maybe grouped/labeled by role in
//   the action -- "from"/"to" for a transfer, etc.) was explicitly
//   deferred by agreement with the user, since no real multi-object
//   action_type exists anywhere yet to design against (see
//   core/ontology/write_mediator.py's own AI-notes, and api/routes.py's
//   own, for where that stands). Revisit this file for real once one
//   does.
// - Verified via a real `npm run build` + `npm run lint` (oxlint) pass
//   at the time this was written, not just visual inspection -- both
//   clean. If picking this back up, re-run both before trusting any
//   further edits compile.
