/**
 * MeaningList -- records ranked by meaning (R45), nearest first.
 *
 * ONE COMPONENT FOR BOTH PLACES: "Related in meaning" under a search,
 * and "Similar records" on an object. Both ask the server for a ranking
 * and show the records it returns, in its order.
 *
 * NO SCORES. A cosine of 0.83 has no meaning a person could act on and
 * differs by model; the order is the whole of what the ranking says.
 *
 * ABSENT WHEN NOT OFFERED. A type that does not declare search by
 * meaning -- or one this person may not use it on -- shows nothing,
 * rather than a section that can only ever say no. When it IS offered
 * but cannot answer now (the model is down, nothing embedded yet), the
 * reason is shown in place of the list.
 */

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { getErrorMessage, handleIfSessionExpired, type MeaningResults } from '@elysium/shell-api/api'
import { getDisplayTitle } from '@elysium/shell-api/format'
import type { VisibleSchema } from '@elysium/shell-api/types'

interface MeaningListProps {
  /** Heading shown above the list when there is something to show. */
  title: string
  objectType: string
  visibleSchema: VisibleSchema | null
  /** Asks the server; called again whenever `requestKey` changes. */
  load: () => Promise<MeaningResults>
  requestKey: string
  /** Said when the ranking found nothing this person may see. */
  emptyText: string
  onSessionExpired: () => void
  /** Wait this long after `requestKey` last changed before asking: a
   *  search box changes on every keystroke, and each question costs a
   *  call to the embedding model. */
  delayMs?: number
}

/** What a ranked record is called: its title field, as everywhere else
 *  -- or, for a type without one, the text the ranking read, which is
 *  WHY it is near. A list of bare ids ("1", "7") says nothing. The id is
 *  shown beside the label whenever it is not the label itself. */
function labelFor(
  typeSchema: Parameters<typeof getDisplayTitle>[0],
  row: { id: string; fields: Record<string, unknown> },
  textFields: string[],
): string {
  const title = String(getDisplayTitle(typeSchema, row.fields, row.id))
  if (title !== row.id) return title
  for (const name of textFields) {
    const value = row.fields[name]
    if (typeof value === 'string' && value.trim() !== '') return value
  }
  return row.id
}

export default function MeaningList({
  title,
  objectType,
  visibleSchema,
  load,
  requestKey,
  emptyText,
  onSessionExpired,
  delayMs = 0,
}: MeaningListProps) {
  const [state, setState] = useState<
    { kind: 'loading' } | { kind: 'done'; data: MeaningResults } | { kind: 'error'; message: string }
  >({ kind: 'loading' })

  useEffect(() => {
    let current = true
    setState({ kind: 'loading' })
    const timer = setTimeout(() => {
      load()
        .then((data) => {
          if (current) setState({ kind: 'done', data })
        })
        .catch((error: unknown) => {
          if (!current || handleIfSessionExpired(error, onSessionExpired)) return
          setState({ kind: 'error', message: getErrorMessage(error) })
        })
    }, delayMs)
    return () => {
      current = false
      clearTimeout(timer)
    }
    // `load` is a new function each render; the key says when to ask again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestKey])

  // NOTHING UNTIL THE ANSWER. A heading shown while asking would flash
  // up and vanish on every object of a type that does not offer this --
  // most of them -- so the section appears only once there is something
  // to say. It sits below the fold; nothing above it moves.
  if (state.kind === 'loading') return null
  if (state.kind === 'error') {
    return (
      <section className="meaning-list">
        <h3>{title}</h3>
        <p className="meaning-list__note">Could not rank by meaning: {state.message}</p>
      </section>
    )
  }
  const { data } = state
  if (data.offered === false) return null
  const typeSchema = visibleSchema?.[objectType]
  return (
    <section className="meaning-list" aria-label={title}>
      <h3>{title}</h3>
      {!data.available ? (
        <p className="meaning-list__note">{data.reason}</p>
      ) : data.results.length === 0 ? (
        <p className="meaning-list__note">{emptyText}</p>
      ) : (
        <ol className="meaning-list__items">
          {data.results.map((row) => {
            const label = labelFor(typeSchema, row, data.text_fields ?? [])
            return (
              <li key={row.id}>
                <Link to={`/objects/${objectType}/${encodeURIComponent(row.id)}`}>{label}</Link>
                {label !== row.id && <span className="meaning-list__id"> {row.id}</span>}
              </li>
            )
          })}
        </ol>
      )}
    </section>
  )
}
