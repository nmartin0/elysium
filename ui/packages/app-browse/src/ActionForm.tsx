import { useState } from 'react'
import { Button, Callout, FormGroup, InputGroup, NumericInput } from '@blueprintjs/core'
import { proposeAction, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
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
  const [values, setValues] = useState<Record<string, string>>(() =>
    // Object.fromEntries + .map(), not a mutable accumulator built up
    // in a for loop -- the same real transform (each parameter name
    // maps to either its locked-in value or an empty string),
    // expressed as one, immutable expression rather than a loop that
    // mutates a local object across iterations. Idiomatic, current
    // TypeScript for exactly this "transform every key/value pair of
    // an object" shape.
    Object.fromEntries(
      Object.entries(actionDef.parameters).map(([paramName, paramSpec]) => [
        paramName,
        // Pre-filled, and left DISABLED below (not just pre-filled
        // and still editable) -- the whole point of opening this form
        // from a specific object's own page is "act on THIS object";
        // letting someone silently retarget it to a different id
        // while still thinking they're acting on the one they
        // navigated to would be confusing at best.
        isLockedToCurrentObject(paramSpec, objectType) ? objectId : '',
      ]),
    ),
  )
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
      // Same Object.fromEntries + .map() shape as the initial values
      // above -- one immutable expression, not a mutable accumulator
      // built up across loop iterations.
      const parameters: Record<string, unknown> = Object.fromEntries(
        Object.entries(actionDef.parameters).map(([paramName, paramSpec]) => {
          const raw = values[paramName]
          return [paramName, paramSpec.type === 'number' && raw !== '' ? Number(raw) : raw]
        }),
      )
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
      setError(getErrorMessage(err))
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
        const fieldId = `action-form-${paramName}`
        return (
          <FormGroup key={paramName} label={formatFieldName(paramName)} labelFor={fieldId}>
            {/* NumericInput/InputGroup, not one <input> with a
                conditional type -- these are genuinely different real
                Blueprint components (different prop shapes entirely:
                onValueChange vs onChange), not a single element that
                takes a type prop the way the original HTML <input>
                did. onValueChange's own second argument (valueAsString)
                is used, not the first (valueAsNumber) -- confirmed
                directly against NumericInput's own type definition
                that this matches this component's own existing design
                exactly: values itself stays Record<string, string>
                throughout, only actually coerced to a real number at
                submit time (see handleSubmit's own comment on why). */}
            {paramSpec.type === 'number' ? (
              <NumericInput
                id={fieldId}
                value={values[paramName]}
                onValueChange={(_valueAsNumber, valueAsString) => handleChange(paramName, valueAsString)}
                disabled={locked}
                required={paramSpec.required}
              />
            ) : (
              <InputGroup
                id={fieldId}
                value={values[paramName]}
                onChange={(event) => handleChange(paramName, event.target.value)}
                disabled={locked}
                required={paramSpec.required}
              />
            )}
          </FormGroup>
        )
      })}
      {error && <Callout intent="danger">{error}</Callout>}
      <div className="action-form__actions">
        {/* loading, not a separate disabled prop -- same real reasoning
            already established for every other Button conversion this
            migration. variant="outlined" for Cancel -- the same de-
            emphasized styling already established for every other
            former className="secondary" button. */}
        <Button type="submit" text="Propose" loading={submitting} />
        <Button type="button" variant="outlined" text="Cancel" onClick={onCancel} disabled={submitting} />
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
// - Blueprint migration: FormGroup/InputGroup/NumericInput/Button,
//   replacing the bare <label>/<input>/<button> elements -- the final
//   step of the whole Blueprint migration roadmap discussed directly
//   with the person, closing it out entirely.
//
//   NumericInput/InputGroup, chosen per-parameter by paramSpec.type,
//   not one element with a conditional type the way the original bare
//   <input> could -- these are genuinely different real Blueprint
//   components (onValueChange vs onChange), confirmed directly
//   against each one's own type definition before writing this, not
//   assumed. A real, confirmed difference from the original HTML
//   input worth remembering: NumericInput does NOT render a real
//   type="number" input -- confirmed directly against its own live
//   DOM output -- it renders type="text" internally and mimics
//   numeric-input behavior via its own JS validation
//   (allowNumericCharactersOnly), exposing role="spinbutton" as the
//   real, accessible signal instead. onValueChange's own second
//   argument (valueAsString), not the first (valueAsNumber), is what
//   this file actually uses -- values itself stays Record<string,
//   string> throughout unchanged, only actually coerced to a real
//   number at submit time, exactly matching this component's own,
//   already-existing design (see handleSubmit's own comment). Two
//   existing tests needed real fixes, not just tolerance, once this
//   difference was confirmed: one asserting a real type="number"
//   attribute (rewritten to assert role="spinbutton" instead, the
//   real, meaningful distinguishing signal), and one asserting a
//   NUMERIC toHaveValue(250)/toHaveValue(null) (rewritten to the real,
//   correct STRING form testing-library itself uses for a type="text"
//   input specifically) -- both confirmed as real, necessary updates
//   via a negative control, not loosened just to make failures go
//   away.
//
//   The error message also converted to Callout intent="danger",
//   matching every other error Callout this whole migration has used
//   -- not explicitly named in the roadmap's own shorthand for this
//   step, but included anyway to close out the one remaining bare
//   <p className="error"> left in the whole app; leaving it would have
//   been a real, visible inconsistency with every other sub-app now.
//
//   Verified live, beyond the unit suite, using a real, multi-object
//   action (TransferFunds) specifically because it has real "number"
//   parameters TO exercise NumericInput with, not just InputGroup:
//   confirmed the locked from_account_id field renders correctly
//   disabled, confirmed both NumericInput fields render with their
//   own real increment/decrement buttons, and confirmed a real,
//   complete submission correctly coerced both entered values to real
//   JSON numbers (not strings) in the resulting, real, multi-object
//   PendingWriteCard.
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
