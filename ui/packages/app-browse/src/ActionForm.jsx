import { useState } from 'react'
import { proposeAction, handleIfSessionExpired } from '@elysium/shell-api/api'
import { formatFieldName } from '@elysium/shell-api/format'
import PendingWriteCard from '@elysium/shell-api/components/PendingWriteCard'

// Stage 3 of the Palantir-parity UI plan: direct, form-driven action
// invocation from an Object View, no LLM involved at all. Owns its
// own small, local lifecycle -- parameter form, then (once proposed)
// the EXISTING PendingWriteCard, reused genuinely unchanged except
// for one small, optional, backward-compatible prop it already
// gained for this purpose (see that file's own comment on
// onResolved). ObjectDetailPanel.jsx only ever needs to know "form
// closed" (onCancel) or "form closed AND the object may have changed"
// (onResolved) -- it never needs to know whether the person got as
// far as seeing a PendingWriteCard at all.
export default function ActionForm({
  actionName,
  actionDef,
  objectType,
  objectId,
  onCancel,
  onResolved,
  onSessionExpired,
}) {
  const [values, setValues] = useState(() => {
    const initial = {}
    for (const [paramName, paramSpec] of Object.entries(actionDef.parameters)) {
      // Pre-filled, and left DISABLED below (not just pre-filled and
      // still editable) -- the whole point of opening this form from
      // a specific object's own page is "act on THIS object";
      // letting someone silently retarget it to a different id while
      // still thinking they're acting on the one they navigated to
      // would be confusing at best. Matches Palantir's own Action
      // widgets, which lock the "acting on this object" parameter the
      // same way when opened from that object's own context.
      initial[paramName] = paramSpec.type === 'object_reference' && paramSpec.object_type === objectType ? objectId : ''
    }
    return initial
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [pendingWrite, setPendingWrite] = useState(null)

  function handleChange(paramName, rawValue) {
    setValues((prev) => ({ ...prev, [paramName]: rawValue }))
  }

  async function handleSubmit(event) {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      // "number" parameters coerced to a real JSON number here -- an
      // HTML number input's own value is always a STRING regardless
      // of type="number"; propose_action() itself does not coerce
      // parameter VALUE types, only presence/absence (see api/
      // routes.py's own docstring on propose_action_route), so a
      // string would silently reach the backend as one otherwise.
      const parameters = {}
      for (const [paramName, paramSpec] of Object.entries(actionDef.parameters)) {
        const raw = values[paramName]
        parameters[paramName] = paramSpec.type === 'number' && raw !== '' ? Number(raw) : raw
      }
      const response = await proposeAction(actionName, parameters)
      setPendingWrite(response.pending_write)
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      // err.message here is ALREADY the safe, generic string api/
      // routes.py's own propose_action_route returns for every real
      // rejection reason (unknown action, RBAC denial, bad
      // parameters, MAC denial) -- deliberately never more specific
      // than that, by design decided with the user. Nothing to
      // sanitize or reword here; display it as-is.
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  if (pendingWrite) {
    return <PendingWriteCard pendingWrite={pendingWrite} onSessionExpired={onSessionExpired} onResolved={onResolved} />
  }

  return (
    <form className="action-form" onSubmit={handleSubmit}>
      <h3>{actionName}</h3>
      {Object.entries(actionDef.parameters).map(([paramName, paramSpec]) => {
        const isLockedToCurrentObject = paramSpec.type === 'object_reference' && paramSpec.object_type === objectType
        return (
          <label key={paramName} className="action-form__field">
            <span>{formatFieldName(paramName)}</span>
            <input
              type={paramSpec.type === 'number' ? 'number' : 'text'}
              value={values[paramName]}
              onChange={(event) => handleChange(paramName, event.target.value)}
              disabled={isLockedToCurrentObject}
              required={paramSpec.required}
            />
          </label>
        )
      })}
      {error && <p className="error">{error}</p>}
      <div className="action-form__actions">
        <button type="submit" disabled={submitting}>
          Propose
        </button>
        <button type="button" className="secondary" onClick={onCancel} disabled={submitting}>
          Cancel
        </button>
      </div>
    </form>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// CONTEXT: Stage 3 -- see api/routes.py's own AI-notes for the
// backend (POST /actions/{action_type_name}), and PendingWriteCard.
// jsx's own comment for the small, optional onResolved addition this
// file is the reason for.
//
// DEFERRED (known, intentional, not yet built):
// - Every OTHER object_reference parameter (one that does NOT match
//   the object this form was opened from -- e.g. TransferFunds'
//   to_account_id when opened from the FROM account's own page) is
//   still a plain text input, not a real object picker. A real
//   picker (search-as-you-type against ObjectSearchPanel's own
//   search_object_free_text() backend) would be a genuine, separate
//   UX improvement -- not built here without a second real,
//   multi-object action in active use to confirm the right shape for
//   it, same discipline PendingWriteCard's own AI-notes already
//   apply to a sub-write's missing "role" label.
// - No client-side validation beyond the browser's own native
//   `required` attribute -- e.g. nothing checks a "number" parameter
//   is actually numeric before submit; an invalid value would surface
//   as this component's own generic error message after a real,
//   rejected request, not a local, pre-submit check. Acceptable for a
//   first pass: propose_action() itself doesn't validate parameter
//   VALUE types either (see this file's own comment above), so a
//   local check here would be enforcing a stricter contract than the
//   backend itself actually promises.
