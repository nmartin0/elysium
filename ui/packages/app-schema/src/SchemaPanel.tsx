/**
 * SchemaPanel -- a read-only view of the ontology this caller can see.
 *
 * Deliberately NOT an editor. Editing the ontology edits the security
 * model: an object type's `security` block is what decides who sees
 * its rows, so "edit what you can see" would not bound the blast
 * radius. See UI_ROADMAP.md.
 *
 * Everything rendered here comes from GET /me/visible-schema, which is
 * already filtered per caller. Fields the caller lacks a grant for are
 * ABSENT rather than marked -- this app cannot know they exist, and
 * that is the uniform denial every other read path uses. Two roles see
 * genuinely different ontologies with no indication anything was
 * withheld.
 */

import { useEffect, useMemo, useState } from 'react'
import { Callout, HTMLTable, Icon, InputGroup, Spinner, Tag } from '@blueprintjs/core'
import { getMyVisibleSchema, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import type { SubAppProps } from '@elysium/shell-api/types'
import './SchemaPanel.css'

interface SchemaField {
  type: string
  display_name: string
  description?: string | null
  visibility?: string
  status?: string
  target?: string | null
  cardinality?: string | null
  link_type?: string | null
}

interface SchemaObjectType {
  display_name: string
  plural_display_name: string
  description?: string | null
  icon?: string | null
  color?: string | null
  status?: string
  group?: string | null
  id_field: string | null
  title_field: string | null
  fields: Record<string, SchemaField>
}

type Schema = Record<string, SchemaObjectType>

/**
 * The three visibility levels, rendered as the reference
 * implementation renders them: prominent properties are spotlighted in
 * their own table, normal ones sit in a regular table, and hidden ones
 * are not shown at all.
 *
 * `hidden` here is COSMETIC. It tells this view not to display a
 * field; it does not withhold one. Field-level grants do that, in the
 * backend, before a value exists -- a hidden field is still in the
 * response precisely so nobody mistakes this for an access control.
 */
const PROMINENT = 'prominent'
const HIDDEN = 'hidden'

function statusIntent(status: string | undefined) {
  if (status === 'deprecated') return 'danger' as const
  if (status === 'experimental') return 'warning' as const
  return 'none' as const
}

function FieldTable({ fields }: { fields: [string, SchemaField][] }) {
  if (fields.length === 0) return null
  return (
    <HTMLTable compact striped className="schema-panel__fields">
      <thead>
        <tr>
          <th>Field</th>
          <th>Type</th>
          <th>Description</th>
        </tr>
      </thead>
      <tbody>
        {fields.map(([apiName, field]) => (
          <tr key={apiName}>
            <td>
              <strong>{field.display_name}</strong>
              {/* The API name is what a caller uses programmatically,
                  and is worth showing -- but only when it differs from
                  the label, or it is the same word twice. */}
              {apiName !== field.display_name && (
                <div className="schema-panel__api-name">{apiName}</div>
              )}
            </td>
            <td>
              {field.type === 'link' ? (
                <>
                  <Tag minimal>link</Tag>{' '}
                  <span>
                    {field.cardinality === 'many' ? 'many' : 'one'} {field.target}
                  </span>
                </>
              ) : (
                <Tag minimal>{field.type}</Tag>
              )}
              {field.status && field.status !== 'active' && (
                <>
                  {' '}
                  <Tag minimal intent={statusIntent(field.status)}>
                    {field.status}
                  </Tag>
                </>
              )}
            </td>
            <td>{field.description ?? ''}</td>
          </tr>
        ))}
      </tbody>
    </HTMLTable>
  )
}

function ObjectTypeCard({ apiName, type }: { apiName: string; type: SchemaObjectType }) {
  const entries = Object.entries(type.fields ?? {})
  const prominent = entries.filter(([, f]) => f.visibility === PROMINENT)
  const normal = entries.filter(([, f]) => (f.visibility ?? 'normal') !== PROMINENT
    && f.visibility !== HIDDEN)

  return (
    <section className="schema-panel__type" data-testid={`object-type-${apiName}`}>
      <h3>
        {type.icon && <Icon icon={type.icon as never} />} {type.display_name}
        {type.status && type.status !== 'active' && (
          <>
            {' '}
            <Tag minimal intent={statusIntent(type.status)}>
              {type.status}
            </Tag>
          </>
        )}
        {type.group && (
          <>
            {' '}
            <Tag minimal>{type.group}</Tag>
          </>
        )}
      </h3>
      {apiName !== type.display_name && (
        <div className="schema-panel__api-name">{apiName}</div>
      )}
      {type.description && <p>{type.description}</p>}

      {prominent.length > 0 && (
        <>
          <h4>Prominent</h4>
          <FieldTable fields={prominent} />
        </>
      )}
      <h4>Properties</h4>
      <FieldTable fields={normal} />
      {entries.length === 0 && (
        <Callout intent="none">
          No fields are visible to you on this object type.
        </Callout>
      )}
    </section>
  )
}

export default function SchemaPanel({ onSessionExpired }: SubAppProps) {
  const [schema, setSchema] = useState<Schema | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState('')

  // Fetches ONCE on mount. Depending on `onSessionExpired` re-runs the
  // effect whenever the shell re-renders, because the shell declares
  // that handler as a plain function -- a new object every time. Your
  // logs showed the schema fetched three times for one page load,
  // which is how this was found: the browser gave no sign of it.
  //
  // `onSessionExpired` is still called from inside, which is safe: the
  // effect closes over the handler current at mount, and the shell's
  // handler only resets auth state.
  //
  // Matches AdminPanel's own pattern rather than changing the shell.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    let cancelled = false
    getMyVisibleSchema()
      .then((body) => {
        if (!cancelled) setSchema(body as Schema)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      })
    return () => {
      cancelled = true
    }
  }, [])

  const matches = useMemo(() => {
    if (!schema) return []
    const needle = filter.trim().toLowerCase()
    return Object.entries(schema)
      .filter(([apiName, type]) =>
        needle === ''
        || apiName.toLowerCase().includes(needle)
        || type.display_name.toLowerCase().includes(needle)
        || (type.group ?? '').toLowerCase().includes(needle))
      .sort(([, a], [, b]) => a.display_name.localeCompare(b.display_name))
  }, [schema, filter])

  if (error) return <Callout intent="danger">{error}</Callout>
  if (!schema) return <Spinner />

  return (
    <div className="schema-panel">
      <InputGroup
        leftIcon="search"
        placeholder="Filter object types..."
        value={filter}
        onChange={(e) => setFilter(e.currentTarget.value)}
      />
      {Object.keys(schema).length === 0 ? (
        <Callout intent="none">
          You do not have read access to any object type in this ontology.
        </Callout>
      ) : matches.length === 0 ? (
        <Callout intent="none">No object type matches {filter}.</Callout>
      ) : (
        matches.map(([apiName, type]) => (
          <ObjectTypeCard key={apiName} apiName={apiName} type={type} />
        ))
      )}
    </div>
  )
}
