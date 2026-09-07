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
import { Button, Callout, HTMLTable, Icon, Spinner, Tab, Tabs, Tag } from '@blueprintjs/core'
import type { SubAppProps } from '@elysium/shell-api/types'
import type { FieldSchema, TypeSchema, VisibleSchema } from '@elysium/app-browse/ObjectDetailPanel'
import ActionTypes from './ActionTypes'
import FilterBox from './FilterBox'
import Discover from './Discover'
import { recordVisit } from './discoverStorage'
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

function FieldTable({
  fields, onOpenObjectType, onOpenLinkType,
}: {
  fields: [string, SchemaField][]
  onOpenObjectType: (objectType: string) => void
  onOpenLinkType: (linkType: string) => void
}) {
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
                  {/* Both halves navigate: the TARGET goes to that
                      object type, the link type goes to the
                      relationship. Reading a schema is mostly
                      following references, and typing each name into a
                      filter by hand is the tedious version of that. */}
                  {field.link_type ? (
                    <Button minimal small onClick={() => onOpenLinkType(field.link_type as string)}>
                      <Tag minimal>link</Tag>
                    </Button>
                  ) : (
                    <Tag minimal>link</Tag>
                  )}{' '}
                  <span>{field.cardinality === 'many' ? 'many' : 'one'}</span>{' '}
                  {field.target ? (
                    <Button minimal small onClick={() => onOpenObjectType(field.target as string)}>
                      {field.target}
                    </Button>
                  ) : (
                    <span>?</span>
                  )}
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

function ObjectTypeCard({
  apiName, type, onOpenObjectType, onOpenLinkType,
}: {
  apiName: string
  type: SchemaObjectType
  onOpenObjectType: (objectType: string) => void
  onOpenLinkType: (linkType: string) => void
}) {
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
          <FieldTable
            fields={prominent}
            onOpenObjectType={onOpenObjectType}
            onOpenLinkType={onOpenLinkType}
          />
        </>
      )}
      <h4>Properties</h4>
      <FieldTable
        fields={normal}
        onOpenObjectType={onOpenObjectType}
        onOpenLinkType={onOpenLinkType}
      />
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
  /** Whose favourites and history to read. Browser storage is
   *  per-machine, so without this a second user on the same browser
   *  would inherit the first's. */
  username: string
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
export default function SchemaPanel({ visibleSchema, username, onSessionExpired }: SchemaPanelProps) {
  const [filter, setFilter] = useState('')
  const [linkFilter, setLinkFilter] = useState('')
  const [actionFilter, setActionFilter] = useState('')
  const [selectedTab, setSelectedTab] = useState<string>('discover')
  // Every cross-reference goes through here: Discover, a link's other
  // end, an action's affected types. One path means one behaviour.
  function openObjectType(objectType: string) {
    recordVisit(username, objectType)
    setFilter(objectType)
    setSelectedTab('object-types')
  }

  function openLinkType(linkType: string) {
    setLinkFilter(linkType)
    setSelectedTab('link-types')
  }

  // Storage is not reactive, so a toggle has to say it happened.
  const [favouriteVersion, setFavouriteVersion] = useState(0)
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
      <Tabs
        id="schema-tabs"
        selectedTabId={selectedTab}
        onChange={(tabId) => {
          // Clicking a tab directly clears its filter. Arriving here
          // from Discover or a cross-reference does NOT, because that
          // navigation sets the filter on purpose.
          //
          // Blueprint's onChange takes a MouseEvent, so it fires only
          // on a real click -- a programmatic selectedTabId change
          // never reaches this.
          const next = String(tabId)
          if (next === 'object-types') setFilter('')
          if (next === 'link-types') setLinkFilter('')
          if (next === 'action-types') setActionFilter('')
          setSelectedTab(next)
        }}
        renderActiveTabPanelOnly
      >
        <Tab
          id="discover"
          title="Discover"
          panel={
            <Discover
              schema={schema}
              username={username}
              version={favouriteVersion}
              onFavouriteChange={() => setFavouriteVersion((n) => n + 1)}
              onOpen={openObjectType}
            />
          }
        />
        <Tab
          id="object-types"
          title="Object types"
          panel={
            <>
              <FilterBox
                value={filter}
                onChange={setFilter}
                placeholder="Filter object types..."
              />
              {Object.keys(schema).length === 0 ? (
                <Callout intent="none">
                  You do not have read access to any object type in this ontology.
                </Callout>
              ) : matches.length === 0 ? (
                <Callout intent="none">No object type matches {filter}.</Callout>
              ) : (
                matches.map(([apiName, type]) => (
                  <ObjectTypeCard
                    key={apiName}
                    apiName={apiName}
                    type={type}
                    onOpenObjectType={openObjectType}
                    onOpenLinkType={openLinkType}
                  />
                ))
              )}
            </>
          }
        />
        <Tab
          id="link-types"
          title="Link types"
          panel={
            <>
              <FilterBox
                value={linkFilter}
                onChange={setLinkFilter}
                placeholder="Filter link types..."
              />
              <LinkTypes
                schema={schema}
                filter={linkFilter}
                onOpenObjectType={openObjectType}
              />
            </>
          }
        />
        <Tab
          id="action-types"
          title="Action types"
          panel={
            <>
              <FilterBox
                value={actionFilter}
                onChange={setActionFilter}
                placeholder="Filter action types..."
              />
              <ActionTypes
                onSessionExpired={onSessionExpired}
                filter={actionFilter}
                onOpenObjectType={openObjectType}
              />
            </>
          }
        />
      </Tabs>
    </div>
  )
}
