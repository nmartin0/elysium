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

import { useEffect, useState } from 'react'
import { Callout, HTMLTable, Spinner, Tag } from '@blueprintjs/core'
import { getVisibleActionTypes, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'

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

export default function ActionTypes({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [actionTypes, setActionTypes] = useState<Record<string, ActionType> | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    getVisibleActionTypes()
      .then((body) => {
        if (!cancelled) setActionTypes(body as Record<string, ActionType>)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
    // Once on mount. onSessionExpired is a new function on every shell
    // render, so depending on it refetches on each one.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (error) return <Callout intent="danger">{error}</Callout>
  if (!actionTypes) return <Spinner />
  if (Object.keys(actionTypes).length === 0) {
    return <p>You cannot execute any action in this ontology.</p>
  }

  return (
    <>
      {Object.entries(actionTypes)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([name, action]) => (
          <section key={name} className="schema-panel__type">
            <h3>{name}</h3>
            {(action.affected_object_types ?? []).length > 0 && (
              <div className="schema-panel__api-name">
                affects {(action.affected_object_types ?? []).join(', ')}
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
