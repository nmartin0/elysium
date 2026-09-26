/**
 * WatchDialog -- what to watch a saved view for, and what to do.
 *
 * THREE QUESTIONS, in the order a person asks them: when should I be
 * told; who else should be told; should anything be proposed. The
 * first is required, the other two are optional -- a trigger that only
 * tells its owner is the common case, and the dialog opens on it.
 *
 * ONLY WHAT THE SERVER WILL ACCEPT IS OFFERED. Actions are filtered to
 * ones this person can run, that do not refuse automation, and that
 * take objects of this view's type; roles to the ones they may name.
 * The server still checks all of it -- this is so the dialog does not
 * offer a choice and then refuse it.
 *
 * AND A REFUSAL IS SHOWN, NOT SWALLOWED. The first version of Watch
 * dropped every error that was not an expired session, which was
 * harmless while nothing could be refused. Now the server validates
 * actions and recipients, so its words have to reach the person.
 */

import {
  Button,
  Checkbox,
  Dialog,
  DialogBody,
  DialogFooter,
  FormGroup,
  HTMLSelect,
  InputGroup,
  NumericInput,
} from '@blueprintjs/core'
import {
  ApiError,
  createTrigger,
  getCurrentUser,
  getDeploymentConfig,
  getErrorMessage,
  getVisibleActionTypes,
  handleIfSessionExpired,
  type ServerSavedView,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { useEffect, useState } from 'react'

import { type ActionChoice, actionsFor, rolesFor, type VisibleAction } from './watchOptions'

interface WatchDialogProps {
  view: ServerSavedView | null
  onClose: () => void
  onSessionExpired?: () => void
}

export default function WatchDialog({ view, onClose, onSessionExpired }: WatchDialogProps) {
  const [thresholdKind, setThresholdKind] = useState('above')
  const [threshold, setThreshold] = useState(10)
  const [actions, setActions] = useState<ActionChoice[]>([])
  const [roles, setRoles] = useState<string[]>([])
  const [recipients, setRecipients] = useState<string[]>([])
  const [actionName, setActionName] = useState('')
  /**
   * The parameter chosen PER ACTION, rather than one string reset by
   * an effect whenever the action changed.
   *
   * That effect was react/set-state-in-effect: switching action
   * rendered once with the previous action's parameter and again with
   * the new default. Keying the choice by action makes the right value
   * DERIVABLE -- a choice made for one action simply is not a choice
   * for another -- so there is nothing to reset and no second render.
   *
   * It also keeps a deliberate choice across a there-and-back switch,
   * which the reset threw away. That is a small improvement rather
   * than the point, and it is tested.
   */
  const [targetByAction, setTargetByAction] = useState<Record<string, string>>({})
  const [values, setValues] = useState<Record<string, string>>({})
  const [refusal, setRefusal] = useState<string | null>(null)
  // WHAT COULD NOT BE LOADED, named rather than hidden. The dialog stays
  // usable -- a trigger that only notifies is still worth making -- but
  // an empty "And propose" would say "no action fits this view" when the
  // truth is "we could not find out". A quiet partial is a wrong answer
  // reporting success, which is the view-state matrix's one rule.
  const [unloaded, setUnloaded] = useState<string[]>([])

  // NO RESET HERE ANY MORE. SavedViews gives this dialog a fresh key
  // per opening, so every instance starts with its own state -- which
  // is both simpler than clearing five setters and complete, where
  // clearing them was not: the threshold was never in that list.
  useEffect(() => {
    if (view === null) return
    void (async () => {
      const failed: string[] = []
      try {
        const visible = (await getVisibleActionTypes()) as Record<string, VisibleAction>
        setActions(actionsFor(visible, view.object_type))
      } catch (caught: unknown) {
        setActions([])
        failed.push(`actions (${getErrorMessage(caught)})`)
      }
      let ownRole: string | null = null
      try {
        const me = (await getCurrentUser()) as { role_name?: string | null }
        ownRole = me.role_name ?? null
      } catch (caught: unknown) {
        failed.push(`your role (${getErrorMessage(caught)})`)
      }
      let allRoles: string[] | null = null
      try {
        const config = (await getDeploymentConfig()) as { role_names?: string[] }
        allRoles = config.role_names ?? null
      } catch (caught: unknown) {
        // A 403 IS THE RULE WORKING, not a failure: without
        // manage:users a person may name only their own role, so it is
        // not reported. Anything else is.
        if (!(caught instanceof ApiError && caught.status === 403)) {
          failed.push(`the list of roles (${getErrorMessage(caught)})`)
        }
      }
      setRoles(rolesFor(ownRole, allRoles))
      setUnloaded(failed)
    })()
  }, [view])

  const chosen = actions.find((action) => action.name === actionName) ?? null

  // Derived during render: this action's own choice, or its own first
  // parameter. Never another action's.
  const target = targetByAction[actionName] ?? chosen?.targets[0] ?? ''

  async function watch() {
    if (view === null) return
    setRefusal(null)
    try {
      await createTrigger({
        name: view.name,
        view_id: view.view_id,
        // ONE THRESHOLD, because the server refuses two.
        above: thresholdKind === 'above' ? threshold : null,
        gained: thresholdKind === 'gained' ? threshold : null,
        fell: thresholdKind === 'fell' ? threshold : null,
        action_type: chosen?.name ?? null,
        action_parameter: chosen ? target : null,
        action_values: chosen ? values : {},
        recipient_roles: recipients,
      })
      onClose()
    } catch (caught: unknown) {
      if (onSessionExpired && handleIfSessionExpired(caught, onSessionExpired)) return
      setRefusal(getErrorMessage(caught))
    }
  }

  return (
    <Dialog isOpen={view !== null} onClose={onClose} title={view === null ? '' : `Watch ${view.name}`}>
      <DialogBody>
        <p>Notify me when this view is</p>
        <div className="saved-views__watch">
          <HTMLSelect
            value={thresholdKind}
            aria-label="When to notify"
            onChange={(event) => setThresholdKind(event.currentTarget.value)}
            options={[
              { value: 'above', label: 'above' },
              { value: 'gained', label: 'gaining' },
              { value: 'fell', label: 'losing' },
            ]}
          />
          <NumericInput
            value={threshold}
            min={1}
            aria-label="How many"
            onValueChange={(value) => setThreshold(Number.isNaN(value) ? 1 : value)}
          />
        </div>

        {roles.length > 0 && (
          <FormGroup label="Also tell" helperText="Each person sees only what they are allowed to.">
            {roles.map((role) => (
              <Checkbox
                key={role}
                label={role}
                checked={recipients.includes(role)}
                onChange={() =>
                  setRecipients((current) =>
                    current.includes(role) ? current.filter((name) => name !== role) : [...current, role],
                  )
                }
              />
            ))}
          </FormGroup>
        )}

        {actions.length > 0 && (
          <FormGroup label="And propose" helperText="Proposed as you, into Approvals. Somebody still decides.">
            <HTMLSelect
              value={actionName}
              aria-label="Action to propose"
              onChange={(event) => {
                setActionName(event.currentTarget.value)
                setValues({})
              }}
              options={[
                { value: '', label: 'nothing' },
                ...actions.map((action) => ({ value: action.name, label: action.name })),
              ]}
            />
          </FormGroup>
        )}

        {chosen !== null && chosen.targets.length > 1 && (
          <FormGroup label="Using the matched objects as">
            <HTMLSelect
              value={target}
              aria-label="Parameter for matched objects"
              onChange={(event) => {
                // READ BEFORE THE UPDATER. React nullifies the synthetic
                // event's currentTarget once the handler returns, and a
                // functional setState runs LATER -- so reading it inside
                // the callback throws "Cannot read properties of null".
                // Caught by the tests added with this change.
                const value = event.currentTarget.value
                setTargetByAction((current) => ({ ...current, [actionName]: value }))
              }}
              options={chosen.targets}
            />
          </FormGroup>
        )}

        {chosen?.others.map(([parameterName, parameter]) => (
          <FormGroup key={parameterName} label={parameter.display_name ?? parameterName}>
            <InputGroup
              aria-label={parameter.display_name ?? parameterName}
              value={values[parameterName] ?? ''}
              onChange={(event) => setValues((current) => ({ ...current, [parameterName]: event.target.value }))}
            />
          </FormGroup>
        ))}

        {/* ErrorState, NOT A BARE DANGER CALLOUT: it carries
            role="alert", so the refusal is ANNOUNCED as well as shown.
            A bare Callout is silent to a screen reader -- and
            tokens.test.ts refused it, which is how this was caught. */}
        {unloaded.length > 0 && (
          <ErrorState>
            {`Could not load ${unloaded.join('; ')} -- so some choices are missing. `}
            {'A trigger that only notifies you can still be made.'}
          </ErrorState>
        )}
        {refusal !== null && <ErrorState>{refusal}</ErrorState>}
      </DialogBody>
      <DialogFooter
        actions={
          <Button intent="primary" onClick={() => void watch()}>
            Watch
          </Button>
        }
      />
    </Dialog>
  )
}
