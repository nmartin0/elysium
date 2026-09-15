/**
 * BulkActionForm -- one action, applied to the objects a person chose.
 *
 * SEPARATE FROM ActionForm RATHER THAN A MODE OF IT. The two have
 * genuinely different shapes: ActionForm fills an object_reference
 * from the page it was opened on, and every parameter is typed by
 * hand. Here the object_reference_list comes from the SELECTION and
 * cannot be typed at all -- there is no sensible control for "paste a
 * thousand ids". Folding them together would mean a form that behaves
 * differently depending on a parameter type nobody can see.
 *
 * WHICH ACTIONS APPEAR IS DECIDED BY THE ONTOLOGY, not by this
 * component. Foundry: "in 'bulk' contexts... only actions that accept
 * object list parameters of the correct type will be shown". An action
 * without a list parameter is not a bulk action, and no amount of UI
 * makes it one.
 *
 * THE COUNT IS RESTATED HERE, deliberately, even though the selection
 * bar already showed it. This is the last screen before a write that
 * touches every one of them, and "apply to 3" and "apply to 900" are
 * the same click.
 */

import { Button, Callout, FormGroup, InputGroup } from '@blueprintjs/core'
import { getErrorMessage, proposeAction } from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { formatFieldName } from '@elysium/shell-api/format'
import { useState } from 'react'

/** DECLARED HERE rather than imported, matching ActionForm.tsx, which
 *  declares its own. The API returns these verbatim from the ontology
 *  -- `type` is whatever the schema says -- so a shared type would
 *  need to stay in step with two moving things. */
interface ParameterSpec {
  type: string
  object_type?: string
  required?: boolean
  display_name?: string
}

interface ActionType {
  name: string
  parameters?: Record<string, ParameterSpec>
}

/** The parameter that receives the selection, if this action has one.
 *  Its absence is what makes an action non-bulk. */
export function listParameterOf(action: ActionType, objectType: string): string | null {
  for (const [name, spec] of Object.entries(action.parameters ?? {})) {
    const parameter = spec as ParameterSpec
    if (parameter.type === 'object_reference_list' && parameter.object_type === objectType) {
      return name
    }
  }
  return null
}

interface BulkActionFormProps {
  action: ActionType
  objectType: string
  /** The ids the action will touch. Already resolved by the caller:
   *  an empty selection means the whole filtered set, and deciding
   *  that here would put the rule in two places. */
  objectIds: string[]
  onDone: () => void
}

export default function BulkActionForm({ action, objectType, objectIds, onDone }: BulkActionFormProps) {
  const [values, setValues] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const listParameter = listParameterOf(action, objectType)

  // TYPED PARAMETERS ONLY. The list one is filled from the selection,
  // so offering an input for it would invite someone to contradict
  // what they just chose.
  const typed = Object.entries(action.parameters ?? {}).filter(([name]) => name !== listParameter)

  async function submit() {
    setSubmitting(true)
    setError(null)
    try {
      await proposeAction(action.name, {
        ...values,
        ...(listParameter === null ? {} : { [listParameter]: objectIds }),
      })
      onDone()
    } catch (err: unknown) {
      // THE SERVER'S OWN WORDS, including its ceiling refusal. The UI
      // warns at 1000 as a courtesy; the server is what enforces it,
      // and its message names the count and the remedy.
      setError(getErrorMessage(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (listParameter === null) {
    // NOT REACHABLE THROUGH THE MENU, which only offers actions that
    // have a list parameter. Stated rather than assumed, because an
    // action rendered here without one would silently write to nothing.
    return (
      <ErrorState>
        {action.name} does not accept a list of {objectType} objects, so it cannot be applied to a selection.
      </ErrorState>
    )
  }

  return (
    <div className="bulk-action-form">
      <Callout intent="primary">
        This will be proposed for {objectIds.length} {objectIds.length === 1 ? objectType : `${objectType} objects`}.
      </Callout>

      {typed.map(([name, spec]) => {
        const parameter = spec as ParameterSpec
        return (
          <FormGroup
            key={name}
            label={parameter.display_name ?? formatFieldName(name)}
            labelInfo={parameter.required ? '(required)' : undefined}
          >
            <InputGroup
              value={values[name] ?? ''}
              onChange={(event) => setValues((current) => ({ ...current, [name]: event.target.value }))}
            />
          </FormGroup>
        )
      })}

      {error !== null && <ErrorState>{error}</ErrorState>}

      <Button
        intent="primary"
        onClick={() => void submit()}
        loading={submitting}
        // NOTHING SELECTED IS NOT A REASON TO DISABLE -- an empty
        // selection means the whole filtered set, and the caller has
        // already resolved that. Zero ids genuinely means zero
        // matches, and proposing against nothing is refused by the
        // server with a better message than this button could give.
        disabled={submitting}
      >
        Propose
      </Button>
    </div>
  )
}
