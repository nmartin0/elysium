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
 * PROJECTED ABOVE (R68): the view's records counted per day, week or
 * month of one of its date fields, forecast, and told when the forecast
 * passes the line. Offered only when the view's type has a date field;
 * it stands alone, so the combining, holding and proposing below are
 * not offered beside it -- the server refuses them.
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
  getDataFreshness,
  getRoleNames,
  getErrorMessage,
  getMyVisibleSchema,
  getSavedViews,
  getVisibleActionTypes,
  handleIfSessionExpired,
  type ServerSavedView,
  type TimePeriod,
  type TriggerCondition,
} from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { type FieldFilter, staleWindowNote } from '@elysium/shell-api/components/FilterBar'
import { useEffect, useState } from 'react'

import { type ActionChoice, actionsFor, rolesFor, type VisibleAction } from './watchOptions'

interface WatchDialogProps {
  view: ServerSavedView | null
  onClose: () => void
  onSessionExpired?: () => void
}

/** One more condition being built: another view, above or at most. */
interface Extra {
  viewId: string
  kind: 'above' | 'at_most'
  count: number
}

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC'
  } catch {
    return 'UTC'
  }
}

export default function WatchDialog({ view, onClose, onSessionExpired }: WatchDialogProps) {
  const [thresholdKind, setThresholdKind] = useState('above')
  const [threshold, setThreshold] = useState(10)
  // PROJECTED ABOVE (R68): which date field, and per what.
  const [dateFields, setDateFields] = useState<{ name: string; label: string }[]>([])
  const [projectedField, setProjectedField] = useState('')
  const [projectedPeriod, setProjectedPeriod] = useState<TimePeriod>('week')
  // COMBINED, HELD OR SCHEDULED (17 October; core/trigger_states.py).
  const [otherViews, setOtherViews] = useState<ServerSavedView[]>([])
  const [extras, setExtras] = useState<Extra[]>([])
  const [combine, setCombine] = useState<'all' | 'any'>('all')
  const [holding, setHolding] = useState(false)
  const [hold, setHold] = useState(1)
  const [holdUnit, setHoldUnit] = useState<'minutes' | 'hours'>('hours')
  const [scheduled, setScheduled] = useState(false)
  const [days, setDays] = useState<number[]>([0, 1, 2, 3, 4])
  const [time, setTime] = useState('09:00')
  // EVERY ACTION THIS PERSON MAY SEE; which are offered depends on whose
  // objects it would receive (below), so it is filtered during render.
  const [visibleActions, setVisibleActions] = useState<Record<string, VisibleAction>>({})
  // WHICH CONDITION'S VIEW GIVES THE ACTION ITS OBJECTS -- '' is this
  // view. Foundry's rule: an action parameter takes the objects a
  // condition exposes, of the matching type (17 October).
  const [actionFrom, setActionFrom] = useState('')
  const [roles, setRoles] = useState<string[]>([])
  const [behindBy, setBehindBy] = useState<number | null>(null)
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
        setVisibleActions(visible)
      } catch (caught: unknown) {
        setVisibleActions({})
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
        // NAMES ONLY, for an account administrator (/roles/names). It was
        // /config until /config became the server's (24 October).
        allRoles = await getRoleNames()
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
      // HOW FAR BEHIND ITS SOURCE THIS TYPE MAY BE (16 October). A
      // watch on "the last 4 hours" of data a day behind can alert on
      // records that changed since -- worth knowing before it is made.
      // Quiet on failure: the note is a caution, not a precondition.
      try {
        // THE OTHER VIEWS THIS PERSON OWNS, for "and also when". Quiet
        // on failure: the dialog still makes a single trigger.
        const mine = await getSavedViews()
        setOtherViews(mine.filter((other) => other.view_id !== view.view_id))
      } catch {
        setOtherViews([])
      }
      try {
        // THE VIEW'S DATE FIELDS, for "projected above". Quiet on
        // failure: the other conditions are still offered.
        const schema = (await getMyVisibleSchema()) as Record<
          string,
          { fields?: Record<string, { data_type?: string; display_name?: string; readable?: boolean }> }
        >
        const fields = Object.entries(schema[view.object_type]?.fields ?? {})
          .filter(([, field]) => ['date', 'timestamp', 'timestamptz'].includes(field.data_type ?? ''))
          .filter(([, field]) => field.readable !== false)
          .map(([name, field]) => ({ name, label: field.display_name ?? name }))
        setDateFields(fields)
      } catch {
        setDateFields([])
      }
      try {
        const freshness = await getDataFreshness()
        setBehindBy(freshness.freshness?.[view.object_type]?.warn_after_hours ?? null)
      } catch {
        setBehindBy(null)
      }
    })()
  }, [view])

  // WHOSE OBJECTS: this view, or one of the added conditions' views --
  // and only actions taking objects of THAT type are offered.
  const actionSourceId = extras.some((extra) => extra.viewId === actionFrom) ? actionFrom : ''
  const actionSource =
    actionSourceId === '' ? view : (otherViews.find((other) => other.view_id === actionSourceId) ?? view)
  const actions: ActionChoice[] = actionSource === null ? [] : actionsFor(visibleActions, actionSource.object_type)
  const chosen = actions.find((action) => action.name === actionName) ?? null
  const stale = view === null ? null : staleWindowNote(view.conditions as unknown as FieldFilter[], behindBy)

  // Derived during render: this action's own choice, or its own first
  // parameter. Never another action's.
  const target = targetByAction[actionName] ?? chosen?.targets[0] ?? ''

  // A STATE (above, at most) can be combined, held or scheduled; a
  // CHANGE (gaining, losing) cannot -- the server refuses it, so it is
  // not offered.
  const isState = thresholdKind === 'above' || thresholdKind === 'at_most'
  const projected = thresholdKind === 'projected'
  const field = projectedField || dateFields[0]?.name || ''

  async function watch() {
    if (view === null) return
    setRefusal(null)
    try {
      await createTrigger({
        name: view.name,
        view_id: view.view_id,
        ...(projected ? { projected_field: field, projected_period: projectedPeriod, projected_above: threshold } : {}),
        // ONE THRESHOLD, because the server refuses two.
        above: thresholdKind === 'above' ? threshold : null,
        gained: thresholdKind === 'gained' ? threshold : null,
        fell: thresholdKind === 'fell' ? threshold : null,
        at_most: thresholdKind === 'at_most' ? threshold : null,
        action_type: projected ? null : (chosen?.name ?? null),
        action_parameter: chosen && !projected ? target : null,
        action_values: chosen && !projected ? values : {},
        ...(chosen && !projected && actionSourceId !== '' ? { action_view_id: actionSourceId } : {}),
        recipient_roles: recipients,
        ...(isState && extras.length > 0
          ? {
              also: extras.map((extra): TriggerCondition =>
                extra.kind === 'above'
                  ? { view_id: extra.viewId, above: extra.count }
                  : { view_id: extra.viewId, at_most: extra.count },
              ),
              combine,
            }
          : {}),
        ...(isState && holding && !scheduled ? { hold_minutes: holdUnit === 'hours' ? hold * 60 : hold } : {}),
        ...(isState && scheduled ? { schedule: { days: [...days].sort(), time }, timezone: browserZone() } : {}),
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
        {stale !== null && (
          <p className="filter-bar__note" role="note">
            {stale}
          </p>
        )}
        <p>Notify me when this view is</p>
        <div className="saved-views__watch">
          <HTMLSelect
            value={thresholdKind}
            aria-label="When to notify"
            onChange={(event) => setThresholdKind(event.currentTarget.value)}
            options={[
              { value: 'above', label: 'above' },
              { value: 'at_most', label: 'at most' },
              { value: 'gained', label: 'gaining' },
              { value: 'fell', label: 'losing' },
              ...(dateFields.length > 0 ? [{ value: 'projected', label: 'projected above' }] : []),
            ]}
          />
          <NumericInput
            value={threshold}
            min={thresholdKind === 'at_most' ? 0 : 1}
            aria-label="How many"
            onValueChange={(value) => setThreshold(Number.isNaN(value) ? 1 : value)}
          />
        </div>
        {projected && (
          // ITS OWN LINE: beside the threshold the four controls did not
          // fit, and their labels were cut off (seen in the browser).
          <div className="watch-projected">
            <span>per</span>
            <HTMLSelect
              aria-label="Per"
              value={projectedPeriod}
              onChange={(event) => setProjectedPeriod(event.currentTarget.value as TimePeriod)}
              options={[
                { value: 'day', label: 'day' },
                { value: 'week', label: 'week' },
                { value: 'month', label: 'month' },
              ]}
            />
            <span>of</span>
            <HTMLSelect
              aria-label="Date field"
              value={field}
              onChange={(event) => setProjectedField(event.currentTarget.value)}
              options={dateFields.map(({ name, label }) => ({ value: name, label }))}
            />
          </div>
        )}
        {projected && (
          <p className="watch-projected__note">
            Its records are counted per {projectedPeriod}, forecast, and you are told when the forecast passes{' '}
            {threshold} — the forecast itself, not the top of its range. A forecast that does not beat carrying the last{' '}
            {projectedPeriod} on warns about nothing.
          </p>
        )}

        {isState && (
          <div className="watch-combined">
            {extras.map((extra, index) => (
              <div className="watch-combined__row" key={index}>
                {index === 0 ? (
                  <HTMLSelect
                    aria-label="Combine"
                    value={combine}
                    onChange={(e) => setCombine(e.currentTarget.value as 'all' | 'any')}
                  >
                    <option value="all">and</option>
                    <option value="any">or</option>
                  </HTMLSelect>
                ) : (
                  <span>{combine === 'all' ? 'and' : 'or'}</span>
                )}
                <HTMLSelect
                  aria-label={`Condition ${index + 2} view`}
                  value={extra.viewId}
                  onChange={(e) => {
                    const viewId = e.currentTarget.value
                    setExtras((current) => current.map((item, at) => (at === index ? { ...item, viewId } : item)))
                  }}
                >
                  {otherViews.map((other) => (
                    <option key={other.view_id} value={other.view_id}>
                      {other.name}
                    </option>
                  ))}
                </HTMLSelect>
                <HTMLSelect
                  aria-label={`Condition ${index + 2} kind`}
                  value={extra.kind}
                  onChange={(e) => {
                    const kind = e.currentTarget.value as 'above' | 'at_most'
                    setExtras((current) => current.map((item, at) => (at === index ? { ...item, kind } : item)))
                  }}
                >
                  <option value="above">above</option>
                  <option value="at_most">at most</option>
                </HTMLSelect>
                <NumericInput
                  aria-label={`Condition ${index + 2} count`}
                  value={extra.count}
                  min={0}
                  onValueChange={(value) =>
                    setExtras((current) =>
                      current.map((item, at) =>
                        at === index ? { ...item, count: Number.isNaN(value) ? 0 : value } : item,
                      ),
                    )
                  }
                />
                <Button
                  minimal
                  small
                  icon="cross"
                  aria-label={`Remove condition ${index + 2}`}
                  onClick={() => setExtras((current) => current.filter((_, at) => at !== index))}
                />
              </div>
            ))}
            {otherViews.length > 0 && extras.length < 9 && (
              <Button
                minimal
                small
                icon="add"
                onClick={() =>
                  setExtras((current) => [...current, { viewId: otherViews[0]!.view_id, kind: 'above', count: 0 }])
                }
              >
                And also when another view is…
              </Button>
            )}

            {!scheduled && (
              <div className="watch-combined__row">
                <Checkbox
                  label="only once it has been true for at least"
                  checked={holding}
                  onChange={() => setHolding((on) => !on)}
                />
                {holding && (
                  <>
                    <NumericInput
                      aria-label="Hold for"
                      value={hold}
                      min={1}
                      onValueChange={(value) => setHold(Number.isNaN(value) ? 1 : value)}
                    />
                    <HTMLSelect
                      aria-label="Hold unit"
                      value={holdUnit}
                      onChange={(e) => setHoldUnit(e.currentTarget.value as 'minutes' | 'hours')}
                    >
                      <option value="minutes">minutes</option>
                      <option value="hours">hours</option>
                    </HTMLSelect>
                  </>
                )}
              </div>
            )}

            <div className="watch-combined__row">
              <Checkbox label="only check on" checked={scheduled} onChange={() => setScheduled((on) => !on)} />
              {scheduled && (
                <>
                  {WEEKDAYS.map((name, day) => (
                    <Checkbox
                      key={name}
                      inline
                      label={name}
                      checked={days.includes(day)}
                      onChange={() =>
                        setDays((current) =>
                          current.includes(day) ? current.filter((d) => d !== day) : [...current, day],
                        )
                      }
                    />
                  ))}
                  <InputGroup
                    aria-label="Check at"
                    type="time"
                    value={time}
                    onChange={(e) => setTime(e.currentTarget.value)}
                  />
                </>
              )}
            </div>
            {scheduled && (
              <p className="watch-combined__note">
                Checked at {time} ({browserZone()}), and you are told every time it is true then.
              </p>
            )}
          </div>
        )}

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

        {isState && extras.length > 0 && (
          <FormGroup label="An action would use the objects of" labelFor="watch-action-from">
            <HTMLSelect
              id="watch-action-from"
              aria-label="Objects for the action"
              value={actionSourceId}
              onChange={(e) => setActionFrom(e.currentTarget.value)}
            >
              <option value="">{view?.name ?? 'this view'}</option>
              {extras.map((extra) => {
                const other = otherViews.find((candidate) => candidate.view_id === extra.viewId)
                return other ? (
                  <option key={extra.viewId} value={extra.viewId}>
                    {other.name}
                  </option>
                ) : null
              })}
            </HTMLSelect>
          </FormGroup>
        )}

        {actions.length > 0 && !projected && (
          <FormGroup
            label="And propose"
            helperText={
              // SAID WHILE CHOOSING (decided 16 October: each action
              // decides): an automation whose every proposal needs a
              // second person is worth knowing about before it is made.
              chosen?.anotherApprover
                ? 'Proposed as you, into Approvals. Someone other than you must approve each one.'
                : 'Proposed as you, into Approvals. Somebody still decides.'
            }
          >
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
