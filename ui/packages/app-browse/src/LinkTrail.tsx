/**
 * LinkTrail -- "Customer Ada Okafor › Transactions", above a view
 * reached by following a link.
 *
 * BY TITLE, as Foundry shows linked objects: "Ada Okafor", not
 * "cust_001", where the type declares a title_field. The id is the
 * fallback, and so it stays if the origin cannot be fetched -- the
 * trail is still TRUE without the title, so a failed fetch is no reason
 * to hide it or to show an error over results that are working.
 *
 * A LINK BACK to the origin, because the point of a trail is that you
 * can walk it.
 */

import { getObjectDetail } from '@elysium/shell-api/api'
import { getDisplayTitle } from '@elysium/shell-api/format'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import type { LinkOrigin } from './linkTrail'

interface LinkTrailProps {
  origin: LinkOrigin
  targetType: string
  visibleSchema: VisibleSchema | null
}

export default function LinkTrail({ origin, targetType, visibleSchema }: LinkTrailProps) {
  /**
   * The fetched title, TAGGED WITH THE OBJECT IT BELONGS TO.
   *
   * This used to be a plain `title` string that the effect reset to
   * origin.id synchronously before fetching -- react/set-state-in-
   * effect, and the reason the rule exists: setting state during an
   * effect starts a second render, so the trail rendered once with the
   * PREVIOUS object's title and again with the id.
   *
   * Tagging removes the reset entirely. Which object a title describes
   * is a fact about the title, and keeping them together means the
   * correct value can be DERIVED below rather than restored by a
   * cleanup nobody can see. A title for an object we are no longer
   * looking at simply does not match, so it is never shown.
   */
  const [fetched, setFetched] = useState<{ id: string; type: string; title: string } | null>(null)

  // Derived during render: no reset, no intermediate frame, and no way
  // for the wrong object's title to be on screen even briefly.
  const title = fetched && fetched.id === origin.id && fetched.type === origin.type ? fetched.title : origin.id

  useEffect(() => {
    let current = true
    void (async () => {
      try {
        const detail = (await getObjectDetail(origin.type, origin.id)) as {
          fields?: Record<string, unknown>
        }
        const shown = getDisplayTitle(visibleSchema?.[origin.type], detail.fields ?? {}, origin.id)
        if (current) setFetched({ id: origin.id, type: origin.type, title: String(shown) })
      } catch {
        // THE ID STAYS: the trail is true without a title. Nothing to
        // reset -- the derivation above already falls back.
      }
    })()
    return () => {
      current = false
    }
  }, [origin.type, origin.id, visibleSchema])

  return (
    <nav aria-label="How you got here" className="link-trail">
      <Link to={`/objects/${origin.type}/${encodeURIComponent(origin.id)}`}>
        {origin.type} {title}
      </Link>
      <span aria-hidden="true" className="link-trail__separator">
        ›
      </span>
      <span>{targetType}</span>
    </nav>
  )
}
