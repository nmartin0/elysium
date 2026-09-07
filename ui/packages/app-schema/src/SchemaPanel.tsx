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

import { useMemo, useState } from 'react'
import { Callout, HTMLTable, Icon, InputGroup, Spinner, Tab, Tabs, Tag } from '@blueprintjs/core'
import type { SubAppProps } from '@elysium/shell-api/types'
import type { FieldSchema, TypeSchema, VisibleSchema } from '@elysium/app-browse/ObjectDetailPanel'
import ActionTypes from './ActionTypes'
import LinkTypes from './LinkTypes'
import './SchemaPanel.css'

// The shared shape, widened where this panel needed more of it. Not
// redeclared here: two definitions of one response is how they drift.
type SchemaField = FieldSchema
type SchemaObjectType = TypeSchema
type Schema = VisibleSchema

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
              <strong>{field.display_name ?? apiName}</strong>
              {/* The API name is what a caller uses programmatically,
                  and is worth showing -- but only when it differs from
                  the label, or it is the same word twice. */}
              {apiName !== (field.display_name ?? apiName) && (
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
        {type.icon && <Icon icon={type.icon as never} />} {type.display_name ?? apiName}
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
      {apiName !== (type.display_name ?? apiName) && (
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

interface SchemaPanelProps extends SubAppProps {
  visibleSchema: Schema | null
}

/**
 * Takes the schema the SHELL already fetched rather than fetching its
 * own, matching ObjectSearchPanel and ObjectDetailPanel.
 *
 * The first version called getMyVisibleSchema() on mount. A server log
 * showed THREE requests per page load, which was traced to an effect
 * dependency -- but the real fault was one level up: the shell holds
 * this data already and hands it to every other panel. Fixing the
 * dependency would have taken three requests down to two, and left the
 * second one just as unnecessary as the third.
 *
 * Worth recording because the first fix was aimed at the symptom the
 * log showed, and the log was pointing at something larger.
 */
export default function SchemaPanel({ visibleSchema, onSessionExpired }: SchemaPanelProps) {
  const [filter, setFilter] = useState('')
  const schema = visibleSchema

  const matches = useMemo(() => {
    if (!schema) return []
    const needle = filter.trim().toLowerCase()
    return Object.entries(schema)
      .filter(([apiName, type]) =>
        needle === ''
        || apiName.toLowerCase().includes(needle)
        || (type.display_name ?? apiName).toLowerCase().includes(needle)
        || (type.group ?? '').toLowerCase().includes(needle))
      .sort(([, a], [, b]) => (a.display_name ?? '').localeCompare(b.display_name ?? ''))
  }, [schema, filter])

  // null means the shell has not finished loading it, not that
  // anything failed -- an empty object is the "you can see nothing"
  // case, handled below.
  if (!schema) return <Spinner />

  return (
    <div className="schema-panel">
      {/* Three resource kinds, matching how the reference
          implementation splits its own ontology browser: object types,
          link types and action types are separately navigable rather
          than one long page. */}
      {/* renderActiveTabPanelOnly, and not only to keep the DOM small:
          without it ActionTypes mounts on page load and fetches
          /me/visible-action-types whether or not anyone opens that
          tab. A hidden panel doing network work is the same class of
          waste this panel was just fixed for. */}
      <Tabs id="schema-tabs" defaultSelectedTabId="object-types" renderActiveTabPanelOnly>
        <Tab
          id="object-types"
          title="Object types"
          panel={
            <>
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
            </>
          }
        />
        <Tab id="link-types" title="Link types" panel={<LinkTypes schema={schema} />} />
        <Tab
          id="action-types"
          title="Action types"
          panel={<ActionTypes onSessionExpired={onSessionExpired} />}
        />
      </Tabs>
    </div>
  )
}
