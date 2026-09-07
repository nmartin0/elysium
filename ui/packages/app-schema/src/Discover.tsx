/**
 * Discover -- a way in, for an ontology too large to scan.
 *
 * Three sections, in the order they are useful: what you marked, what
 * you looked at, and what the ontology itself says is current.
 *
 * The third needs no storage at all. An object type's `status` is
 * declared by the ontology author -- active, experimental, deprecated
 * -- so "active" IS the prominent set, and deprecated types are worth
 * showing separately rather than mixed in.
 *
 * Every list here is filtered through the CURRENT visible schema, so a
 * permission change takes effect immediately in both directions. See
 * discoverStorage's own header for why that is a read-time filter
 * rather than a stored reconciliation.
 */

import { Button, Callout, Tag } from '@blueprintjs/core'
import type { VisibleSchema } from '@elysium/shell-api/types'

import { getFavourites, getRecent, isFavourite, toggleFavourite } from './discoverStorage'

interface DiscoverProps {
  schema: VisibleSchema
  username: string
  onOpen: (objectType: string) => void
  /** Bumped by the parent so toggling a favourite re-reads storage. */
  version: number
  onFavouriteChange: () => void
}

function TypeList({
  names, schema, onOpen, username, onFavouriteChange, empty,
}: {
  names: string[]
  schema: VisibleSchema
  onOpen: (objectType: string) => void
  username: string
  onFavouriteChange: () => void
  empty: string
}) {
  if (names.length === 0) return <p className="schema-panel__api-name">{empty}</p>
  return (
    <div className="schema-panel__discover-list">
      {names.map((name) => (
        <span key={name} className="schema-panel__discover-item">
          <Button minimal small onClick={() => onOpen(name)}>
            {schema[name]?.display_name ?? name}
          </Button>
          <Button
            minimal
            small
            icon={isFavourite(username, name) ? 'star' : 'star-empty'}
            aria-label={`Favourite ${name}`}
            onClick={() => {
              toggleFavourite(username, name)
              onFavouriteChange()
            }}
          />
        </span>
      ))}
    </div>
  )
}

export default function Discover({
  schema, username, onOpen, version, onFavouriteChange,
}: DiscoverProps) {
  // `version` is read so this recomputes when a favourite is toggled;
  // storage is not reactive on its own.
  void version

  const visibleTypes = Object.keys(schema)
  const favourites = getFavourites(username, visibleTypes)
  const recent = getRecent(username, visibleTypes)
  const deprecated = visibleTypes.filter((name) => schema[name]?.status === 'deprecated')
  const active = visibleTypes
    .filter((name) => (schema[name]?.status ?? 'active') === 'active')
    .sort((a, b) => (schema[a]?.display_name ?? a).localeCompare(schema[b]?.display_name ?? b))

  if (visibleTypes.length === 0) {
    return (
      <Callout intent="none">
        You do not have read access to any object type in this ontology.
      </Callout>
    )
  }

  return (
    <div className="schema-panel__discover">
      <h4>Favourites</h4>
      <TypeList
        names={favourites} schema={schema} onOpen={onOpen} username={username}
        onFavouriteChange={onFavouriteChange}
        empty="Star an object type to keep it here."
      />

      <h4>Recently viewed</h4>
      <TypeList
        names={recent} schema={schema} onOpen={onOpen} username={username}
        onFavouriteChange={onFavouriteChange}
        empty="Object types you open will appear here."
      />

      <h4>All active</h4>
      <TypeList
        names={active} schema={schema} onOpen={onOpen} username={username}
        onFavouriteChange={onFavouriteChange}
        empty="No active object types."
      />

      {deprecated.length > 0 && (
        <>
          <h4>
            Deprecated <Tag minimal intent="danger">{deprecated.length}</Tag>
          </h4>
          <TypeList
            names={deprecated} schema={schema} onOpen={onOpen} username={username}
            onFavouriteChange={onFavouriteChange}
            empty=""
          />
        </>
      )}
    </div>
  )
}
