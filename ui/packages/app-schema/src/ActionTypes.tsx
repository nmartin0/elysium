/**
 * Action types: what a caller may propose, and what each one needs.
 *
 * Fetched here rather than taken from the shell, unlike the schema --
 * the shell does not hold action types, and only this panel and the
 * write flow need them. Adding them to the shell would put a fetch on
 * every page load for data two screens use.
 *
 * Shows only what GET /me/visible-action-types returns, which is
 * already filtered: an action the caller cannot execute is absent, not
 * disabled. Same uniform denial the rest of the app uses.
 *
 * Deliberately does NOT render sub_writes. Those describe HOW an
 * action mutates data -- object ids, mutation targets, submission
 * criteria -- which is implementation detail an operator does not need
 * and which reveals more about internal structure than a read-only
 * browser should.
 */

import { Button, Callout, HTMLTable, Spinner, Tag } from '@blueprintjs/core'
import { useEffect, useState } from 'react'
import { getVisibleActionTypesCached, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'

interface ActionParameter {
  type: string
  object_type?: string | null
  required?: boolean | null
  default_to_current_object?: boolean | null
  display_name?: string | null
  description?: string | null
}

interface ActionType {
  affected_object_types?: string[]
  parameters?: Record<string, ActionParameter>
}

interface ActionTypesProps {
  onSessionExpired: () => void
  filter: string
  /** Opens an object type -- the ones an action affects are usually
   *  the next thing you want to see. */
  onOpenObjectType: (objectType: string) => void
}

export default function ActionTypes({
  onSessionExpired, filter, onOpenObjectType,
}: ActionTypesProps) {
  const [actionTypes, setActionTypes] = useState<Record<string, ActionType> | null>(null)
  const [error, setError] = useState<string | null>(null)

  // No stale-response guard, matching AdminPanel. This effect runs
  // ONCE on mount, so there is no second request whose result could
  // arrive out of order -- which is the only thing
  // useLatestRequestGuard exists to prevent.
  useEffect(() => {
    getVisibleActionTypesCached()
      .then((body) => setActionTypes(body as Record<string, ActionType>))
      .catch((err: unknown) => {
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) return <Callout intent="danger">{error}</Callout>
  if (!actionTypes) return <Spinner />
  if (Object.keys(actionTypes).length === 0) {
    return <p>You cannot execute any action in this ontology.</p>
  }

  const needle = filter.trim().toLowerCase()
  const matches = Object.entries(actionTypes)
    .filter(([name, action]) =>
      needle === ''
      || name.toLowerCase().includes(needle)
      || (action.affected_object_types ?? []).some((type) => type.toLowerCase().includes(needle))
      || Object.keys(action.parameters ?? {}).some((param) => param.toLowerCase().includes(needle)))
    .sort(([a], [b]) => a.localeCompare(b))

  if (matches.length === 0) {
    return <p>No action type matches {filter}.</p>
  }

  return (
    <>
      {matches.map(([name, action]) => (
          <section key={name} className="schema-panel__type">
            <h3>{name}</h3>
            {(action.affected_object_types ?? []).length > 0 && (
              <div className="schema-panel__api-name">
                affects{' '}
                {(action.affected_object_types ?? []).map((type) => (
                  <Button key={type} minimal small onClick={() => onOpenObjectType(type)}>
                    {type}
                  </Button>
                ))}
              </div>
            )}
            <HTMLTable compact striped className="schema-panel__fields">
              <thead>
                <tr>
                  <th>Parameter</th>
                  <th>Type</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(action.parameters ?? {}).map(([paramName, parameter]) => (
                  <tr key={paramName}>
                    <td>
                      <strong>{parameter.display_name ?? paramName}</strong>
                      {parameter.display_name && parameter.display_name !== paramName && (
                        <div className="schema-panel__api-name">{paramName}</div>
                      )}
                    </td>
                    <td>
                      <Tag minimal>{parameter.type}</Tag>
                      {parameter.object_type && <> {parameter.object_type}</>}
                      {parameter.required && (
                        <>
                          {' '}
                          <Tag minimal intent="primary">
                            required
                          </Tag>
                        </>
                      )}
                    </td>
                    <td>{parameter.description ?? ''}</td>
                  </tr>
                ))}
              </tbody>
            </HTMLTable>
          </section>
      ))}
    </>
  )
}
