/**
 * ExploreRelated -- where each link leads, and how far.
 *
 * COUNTS BEFORE EXPANSION, which is the whole design. A person
 * deciding whether to follow a link needs to know it leads to four
 * things or four thousand BEFORE they commit. An explorer that expands
 * first and apologises afterwards is unusable on real data.
 *
 * ONE HOP AT A TIME, DELIBERATELY. Not a graph canvas: no automatic
 * multi-hop expansion, no layout, no drag-to-rearrange. Those are the
 * "full Vertex" item in ROADMAP.md, and reaching them by accident --
 * by letting one expansion trigger the next -- is how a read-only
 * explorer becomes something nobody can reason about on a real
 * ontology.
 *
 * WHAT A COUNT MEANS HERE is what YOU would receive. MAC and RBAC
 * apply on the far side, so a count never promises rows a person
 * cannot then open, and never discloses the size of data they may not
 * see.
 */

import { Tag } from '@blueprintjs/core'
import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'

import { getErrorMessage, getLinkCounts, handleIfSessionExpired, type LinkCount } from '@elysium/shell-api/api'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import { formatFieldName } from '@elysium/shell-api/format'
import type { VisibleSchema } from '@elysium/shell-api/types'

interface ExploreRelatedProps {
  objectType: string
  objectId: string
  visibleSchema: VisibleSchema | null
  onSessionExpired: () => void
}

/** The field on `target` that points back at `objectType`.
 *
 * NEEDED BECAUSE A FILTER RUNS ON THE TARGET. To see cust_001's
 * transactions you filter Transaction on `customer_id` -- the REVERSE
 * field -- not on Customer's own `transactions`. Verified directly:
 * filtering Transaction on `transactions` is refused as invalid search
 * criteria, so a link built from the forward field name would have
 * been a dead end that looked live.
 *
 * Returns null when no reverse link is declared, and the caller then
 * shows the count without offering navigation. An honest count beats a
 * link that goes nowhere.
 */
function reverseLinkField(schema: VisibleSchema | null, target: string, objectType: string): string | null {
  const fields = schema?.[target]?.fields
  if (!fields) return null
  for (const [name, info] of Object.entries(fields)) {
    if (info.type === 'link' && info.target === objectType) return name
  }
  return null
}

export default function ExploreRelated({ objectType, objectId, visibleSchema, onSessionExpired }: ExploreRelatedProps) {
  const [links, setLinks] = useState<Record<string, LinkCount> | null>(null)
  const [error, setError] = useState<string | null>(null)

  // The session callback through a ref, so this effect does not
  // restart every time the shell re-renders -- App.tsx declares
  // handleSessionExpired as a plain function inside the component, so
  // it is a new identity each time. Patch 12 fixed seven of these; its
  // guard matched only the callback ALONE in a dependency array, so
  // these two, where it sits beside other dependencies, were missed.
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  useEffect(() => {
    let stale = false
    setLinks(null)
    setError(null)

    getLinkCounts(objectType, objectId)
      .then((result) => {
        if (!stale) setLinks(result)
      })
      .catch((caught) => {
        if (stale) return
        // Checked by STATUS, not by searching the message for "401".
        //
        // The string test could never fire for the case it was written
        // for: api/auth_dependency.py answers an expired session with
        // detail "Invalid or expired session", a sentence with no
        // digits in it, and api.ts puts that detail in the message. It
        // was also wrong the other way -- any message that happened to
        // contain "401", an id or a count, logged the person out.
        //
        // handleIfSessionExpired reads err.status on a real ApiError
        // instance, which is the thing actually being asked about.
        if (handleIfSessionExpired(caught, latestSessionExpired.current)) return
        setError(getErrorMessage(caught))
      })

    // Guards against a slow response for the PREVIOUS object landing
    // after a faster one for the object now on screen -- which would
    // show one record's links under another's name.
    return () => {
      stale = true
    }
  }, [objectType, objectId])

  if (error !== null) return <ErrorState>{error}</ErrorState>
  if (links === null) return <LoadingState inline label="Counting related records…" />

  const entries = Object.entries(links)
  if (entries.length === 0) {
    // NOT AN ERROR, and not empty-looking either. An object with no
    // links you can follow is an ordinary state, and saying so is
    // better than a blank area that reads as a failed render.
    return <p className="explore-related__none">Nothing links from this record.</p>
  }

  return (
    <ul className="explore-related">
      {entries.map(([field, link]) => {
        const reverse = reverseLinkField(visibleSchema, link.target, objectType)
        const label = `${link.count} ${link.target}`

        return (
          <li key={field} className="explore-related__link">
            <span className="explore-related__label">{formatFieldName(field)}</span>
            {link.count === 0 || reverse === null ? (
              // NO LINK WHEN THERE IS NOWHERE TO GO. A clickable row
              // leading to an empty result is a promise the data does
              // not keep -- and without a reverse field there is no
              // filter to express the question, so the count is shown
              // plainly rather than made to look navigable.
              <Tag minimal>{link.count === 0 ? 'None' : label}</Tag>
            ) : (
              <Link
                className="explore-related__go"
                // `from` CARRIES THE ORIGIN, so Browse can say how you got
                // there -- Foundry's link filter, distinct from a property
                // filter. JSON, because ids may contain `/`.
                to={`/browse?type=${link.target}&from=${encodeURIComponent(
                  JSON.stringify({ type: objectType, id: objectId, field: reverse }),
                )}&filters=${encodeURIComponent(
                  JSON.stringify([{ field: reverse, values: [objectId], mode: 'keep' }]),
                )}`}
              >
                <Tag intent="primary" interactive>
                  {label}
                </Tag>
              </Link>
            )}
          </li>
        )
      })}
    </ul>
  )
}
