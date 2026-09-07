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

// Cached at MODULE level, not in component state.
//
// renderActiveTabPanelOnly unmounts this panel when you switch tabs,
// so component state dies with it and every return to the tab
// refetched. A real log showed six requests for three visits. Trading
// a fetch-on-page-load for a fetch-per-visit is not an improvement --
// it just moves when the waste happens.
//
// Module level rather than a context or a query library: this is one
// endpoint, read by one panel, whose contents change only when the
// deployment's YAML does. A reload picks up a change, which is the
// same freshness every other schema read in this app has.
let cached: Record<string, ActionType> | null = null

/** Clears the module cache. For tests, which would otherwise share it
 *  across cases -- the real hazard of module-level state, and worth
 *  making explicit rather than leaving each test to discover. */
export function resetActionTypeCache(): void {
  cached = null
}

export default function ActionTypes({ onSessionExpired }: { onSessionExpired: () => void }) {
  const [actionTypes, setActionTypes] = useState<Record<string, ActionType> | null>(cached)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (cached !== null) return
    let cancelled = false
    getVisibleActionTypes()
      .then((body) => {
        cached = body as Record<string, ActionType>
        if (!cancelled) setActionTypes(cached)
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
