import { useState } from 'react'
import { confirmWrite, ApiError } from '../api'

// "balance" stays "Balance"; "reopen_reason" becomes "Reopen reason"
// -- every real field name in this project's own schemas (balance,
// name, email, region, status, reopen_reason, subject, category, ...)
// reads correctly through this one, simple transformation. NOT
// Title Case for multi-word names -- the frontend-design skill's own
// guidance against needless ALL CAPS labels applies equally to
// needless Title Case; sentence case is the plainer, less templated
// choice.
function formatFieldName(name) {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

function formatValue(value) {
  if (value === null || value === undefined) return '(not set)'
  return String(value)
}

// One object's own field-by-field changes, as a real "old -> new"
// transition per field when the backend supplied one (expected_
// current_values is empty for a "create" sub_write -- nothing
// existed yet to have an old value, correctly rendered as just the
// new value, not an error or a missing-data placeholder).
function SubWriteFields({ subWrite }) {
  return (
    <dl className="pending-write__fields">
      {Object.keys(subWrite.changes).map((field) => {
        const hasOldValue = Object.prototype.hasOwnProperty.call(
          subWrite.expected_current_values ?? {}, field
        )
        return (
          <div key={field} className="pending-write__field">
            <dt>{formatFieldName(field)}</dt>
            <dd>
              {hasOldValue && (
                <span className="pending-write__old-value">
                  {formatValue(subWrite.expected_current_values[field])}
                  {' \u2192 '}
                </span>
              )}
              {formatValue(subWrite.changes[field])}
            </dd>
          </div>
        )
      })}
    </dl>
  )
}

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

  // A single-object action gets no extra visual boundary around its
  // own fields -- there's nothing else on the card to distinguish it
  // FROM, so a boundary there would be decoration, not information
  // (see the frontend-design skill's own "visual structure is
  // information" principle). Only once a REAL action touches more
  // than one object -- proven possible by TransferFunds, not just
  // theoretical -- does each one get its own labeled section.
  const isMultiObject = pendingWrite.sub_writes.length > 1

  return (
    <div className="pending-write">
      <h3>Proposed change</h3>
      <p className="pending-write__description">{pendingWrite.description}</p>
      {pendingWrite.sub_writes.map((subWrite, i) =>
        isMultiObject ? (
          <div key={i} className="pending-write__object">
            <p className="pending-write__object-label">
              {subWrite.object_type} {subWrite.object_id}
            </p>
            <SubWriteFields subWrite={subWrite} />
          </div>
        ) : (
          <SubWriteFields key={i} subWrite={subWrite} />
        )
      )}
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
// RESOLVED (kept for history):
// - The real, polished multi-object confirmation UI this file's own
//   earlier notes deferred -- built once TransferFunds existed as a
//   real multi-object action to design against (see core/ontology/
//   write_mediator.py's own AI-notes for that history). Each object
//   gets its own labeled section ONLY when there's more than one --
//   see isMultiObject above for why a single-object action stays
//   exactly as plain as before, deliberately: an extra border/section
//   around the ONLY thing on the card distinguishes nothing.
// - api/routes.py's own pending-write response was extended with
//   expected_current_values per sub_write (a real, previously-unused
//   field SubWrite already had -- see that file's own AI-notes) so
//   this UI could show a genuine "old -> new" transition per field,
//   not just the new value in isolation. A real backend change, not
//   UI-only -- justified because a bare new value ("balance: 450") is
//   a meaningfully weaker confirmation than the transition itself
//   ("balance: 500 -> 450"), especially for something like a transfer
//   where the DELTA is what a person actually needs to verify before
//   approving. Empty for "create" sub_writes (nothing existed yet to
//   have an old value) -- rendered as just the new value, not an
//   error or a placeholder.
// - Verified via a real `npm run build` + `npm run lint` (oxlint) pass,
//   not just visual inspection -- both clean. If picking this back up,
//   re-run both before trusting any further edits compile.
//
// DEFERRED (known, intentional, not yet built):
// - Still no semantic "role" labeling for a sub_write within its own
//   action (e.g. "From"/"To" for a transfer, rather than the generic
//   object_type + object_id header) -- the schema has no place to
//   declare this today (sub_writes are an unordered-in-spirit list,
//   see core/ontology/action_types.py's own shape), and TransferFunds
//   itself doesn't distinguish "from" and "to" in its own sub_writes
//   beyond their order and which parameter resolved each object_id.
//   Would need a real schema addition (e.g. an optional "label" per
//   sub_write) to do properly -- not invented here without a second
//   real action to confirm the shape is actually the right one.
