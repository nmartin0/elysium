/**
 * Where this object's row came from.
 *
 * DEV_UI.md section 5 item 5: "A PROVENANCE PANEL: which source, which
 * bronze snapshot, which publication, when. The lineage for this now
 * exists." It does, and since the previous patch there is a route that
 * reads it back. And item 3 says where it belongs: "THE OBJECT VIEW AS
 * A HUB: properties, links, history, notes, provenance and the actions
 * available on THIS object, together."
 *
 * MOST READERS WILL NEVER SEE THIS, by design rather than by accident.
 * `_silo` and `_source_table` name the customer's own systems, and
 * `/silos` already treats those names as `manage:users`-only, so the
 * route is gated the same way. A 403 here is the ordinary case, and the
 * panel renders NOTHING for it -- no empty state, no "not permitted",
 * no hint that there is a thing being withheld.
 *
 * WHICH IS THE OPPOSITE OF WHAT THE FIELD TABLE DOES, deliberately, and
 * the distinction is worth keeping straight. A withheld FIELD says "Not
 * permitted", because the reader can see the object and comparing two
 * of them should not silently differ. This panel is not about the
 * object at all -- it is about the deployment's plumbing, and somebody
 * who may not administer the deployment gains nothing from learning
 * that a provenance panel exists.
 */

import { useEffect, useState } from 'react'

import { getObjectProvenance, type ObjectProvenance } from '@elysium/shell-api/api'

export default function Provenance({ objectType, objectId }: { objectType: string; objectId: string }) {
  const [lineage, setLineage] = useState<ObjectProvenance | null>(null)

  useEffect(() => {
    let cancelled = false
    getObjectProvenance(objectType, objectId)
      .then((found) => {
        if (!cancelled) setLineage(found)
      })
      .catch(() => {
        // REFUSED, OR UNREACHABLE, AND BOTH RENDER THE SAME NOTHING.
        // Distinguishing them on screen would tell a reader without the
        // grant that the grant exists.
        if (!cancelled) setLineage(null)
      })
    return () => {
      cancelled = true
    }
  }, [objectType, objectId])

  if (!lineage) return null

  // A LIVE-READ DEPLOYMENT HAS NO LINEAGE AT ALL and the route answers
  // with every field absent rather than an error. Nothing to show is
  // nothing to show.
  const rows = [
    ['Silo', lineage.silo],
    ['Source table', lineage.source_table],
    ['Bronze snapshot', lineage.bronze_snapshot_id],
    ['Row hash', lineage.row_hash],
  ].filter(([, value]) => value)

  if (rows.length === 0) return null

  return (
    <section className="object-detail__provenance">
      <h3>Where this came from</h3>
      <dl className="provenance">
        {rows.map(([label, value]) => (
          <div key={label} className="provenance__row">
            <dt>{label}</dt>
            {/* MONOSPACE, because every one of these is an identifier
                somebody will compare against another system by eye --
                a silo name against a connection string, a snapshot id
                against a sync log. */}
            <dd className="provenance__value">{value}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}
