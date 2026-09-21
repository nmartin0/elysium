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
  const [title, setTitle] = useState<string>(origin.id)

  useEffect(() => {
    setTitle(origin.id)
    let current = true
    void (async () => {
      try {
        const detail = (await getObjectDetail(origin.type, origin.id)) as {
          fields?: Record<string, unknown>
        }
        const shown = getDisplayTitle(visibleSchema?.[origin.type], detail.fields ?? {}, origin.id)
        if (current) setTitle(String(shown))
      } catch {
        // THE ID STAYS: the trail is true without a title.
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
