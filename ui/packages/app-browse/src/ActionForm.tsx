import { useState } from 'react'
import { proposeAction, handleIfSessionExpired } from '@elysium/shell-api/api'
import { formatFieldName } from '@elysium/shell-api/format'
import PendingWriteCard, { type PendingWrite } from '@elysium/shell-api/components/PendingWriteCard'

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

// Not exported -- confirmed via knip that nothing imports this by
// name anywhere else; every other file that constructs a parameter
// spec relies on TypeScript's own structural typing against the
// inline shape, not a named import of this interface. ActionDef
// itself (below) IS exported, since ObjectDetailPanel.jsx genuinely
// imports that one by name.
interface ParameterSpec {
  type: string
  required?: boolean
  object_type?: string
  default_to_current_object?: boolean
}

// The real shape of ONE entry in the backend's own GET /me/visible-
// action-types response (see api/routes.py's own docstring). Exported
// here, not kept local -- this component only ever reads its own
// `parameters`, but ObjectDetailPanel.jsx (a KNOWN, not speculative,
// future consumer -- it's what actually fetches visibleActionTypes
// and passes ONE entry through as this component's own actionDef
// prop) also reads affected_object_types/executable on the exact SAME
// real object, to decide which action buttons to offer at all. One
// accurate, shared type for the real, whole shape, not two partial
// ones describing the same object that could quietly drift apart.
export interface ActionDef {
  affected_object_types: string[]
  executable: boolean
  parameters: Record<string, ParameterSpec>
}

// A parameter is pre-filled and locked to the CURRENT object ONLY
// when BOTH of these hold, not either alone:
//   1. its own schema explicitly marks it default_to_current_object
//      (core/ontology/action_types.py's own validation guarantees at
//      most one parameter per action carries this -- see that
//      module's own docstring for the real bug this replaced: type-
//      matching alone locked EVERY object_reference parameter of a
//      given type, which silently broke the moment an action had two
//      of them, e.g. TransferFunds' own from_account_id/to_account_id
//      both referencing Account).
//   2. that parameter's own object_type genuinely matches the type of
//      object THIS form was actually opened from -- an action with
//      MULTIPLE affected_object_types could be launched from any one
//      of them, and the marked parameter's own type won't always be
//      the one that matches; pre-filling it with an id of the WRONG
//      type would be a real, silent correctness bug of its own, not
//      just a UX one.
function isLockedToCurrentObject(paramSpec: ParameterSpec, objectType: string): boolean {
  return (
    paramSpec.type === 'object_reference' &&
    paramSpec.default_to_current_object === true &&
    paramSpec.object_type === objectType
  )
}

interface ActionFormProps {
  actionName: string
  actionDef: ActionDef
  objectType: string
  objectId: string
  onCancel: () => void
  onResolved: (approved: boolean) => void
  onSessionExpired: () => void
}

export default function ActionForm({
  actionName,
  actionDef,
  objectType,
  objectId,
  onCancel,
  onResolved,
  onSessionExpired,
}: ActionFormProps) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {}
    for (const [paramName, paramSpec] of Object.entries(actionDef.parameters)) {
      // Pre-filled, and left DISABLED below (not just pre-filled and
      // still editable) -- the whole point of opening this form from
      // a specific object's own page is "act on THIS object";
      // letting someone silently retarget it to a different id while
      // still thinking they're acting on the one they navigated to
      // would be confusing at best.
      initial[paramName] = isLockedToCurrentObject(paramSpec, objectType) ? objectId : ''
    }
    return initial
  })
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pendingWrite, setPendingWrite] = useState<PendingWrite | null>(null)

  function handleChange(paramName: string, rawValue: string) {
    setValues((prev) => ({ ...prev, [paramName]: rawValue }))
  }

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
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
      const parameters: Record<string, unknown> = {}
      for (const [paramName, paramSpec] of Object.entries(actionDef.parameters)) {
        const raw = values[paramName]
        parameters[paramName] = paramSpec.type === 'number' && raw !== '' ? Number(raw) : raw
      }
      // proposeAction() itself returns Promise<unknown> (see api.ts's
      // own header comment on why) -- asserted to the real, known
      // success shape here, matching api/routes.py's own documented
      // contract for propose_action_route's 202 response.
      const response = (await proposeAction(actionName, parameters)) as { pending_write: PendingWrite }
      setPendingWrite(response.pending_write)
    } catch (err) {
      if (handleIfSessionExpired(err, onSessionExpired)) return
      // err.message here is ALREADY the safe, generic string api/
      // routes.py's own propose_action_route returns for every real
      // rejection reason (unknown action, RBAC denial, bad
      // parameters, MAC denial) -- deliberately never more specific
      // than that, by design decided with the user. Nothing to
      // sanitize or reword here; display it as-is.
      setError(err instanceof Error ? err.message : String(err))
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
        const locked = isLockedToCurrentObject(paramSpec, objectType)
        return (
          <label key={paramName} className="action-form__field">
            <span>{formatFieldName(paramName)}</span>
            <input
              type={paramSpec.type === 'number' ? 'number' : 'text'}
              value={values[paramName]}
              onChange={(event) => handleChange(paramName, event.target.value)}
              disabled={locked}
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
// RESOLVED (kept for history):
// - A real, previously-undiscovered functional bug, found while
//   writing this file's own test suite (ActionForm.test.jsx),
//   documented there directly before being fixed: the old locking
//   check (`paramSpec.object_type === objectType`, with no marker at
//   all) locked EVERY object_reference parameter whose own
//   object_type matched the current page, not just the one the form
//   was genuinely opened from. TransferFunds' own from_account_id AND
//   to_account_id both reference Account -- both used to get
//   pre-filled and disabled with the SAME account's id, leaving no
//   way to specify a different "to" account through the form at all.
//   Fixed via a real, explicit, per-parameter schema marker
//   (default_to_current_object -- see core/ontology/action_types.py's
//   own docstring for the full design and its own validation),
//   confirmed directly against Palantir Foundry's own documented
//   mechanism for exactly this case before designing it (their own
//   Action-widget "Default value" -> "Environment variable" ->
//   "Current object" binding -- also explicit, by parameter identity,
//   never inferred from type alone). isLockedToCurrentObject() now
//   checks BOTH the marker AND the type-match, not either alone -- an
//   action with MULTIPLE affected_object_types could be opened from
//   any one of them, and the marked parameter's own type won't always
//   be the one that matches; the type-match half of the check is what
//   keeps this correct in that case too, not just a redundant
//   leftover from the old logic.
// - ActionDef/ParameterSpec -- the shared prop-type shape for one
//   visible-action-types entry -- exported from THIS file (see this
//   file's own top-of-file comment for why here) once the TypeScript
//   migration reached this component.
//
// DEFERRED (known, intentional, not yet built):
// - Every OTHER object_reference parameter (one that isn't locked to
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
