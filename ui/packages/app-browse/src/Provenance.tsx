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

import DataTable from '@elysium/shell-api/components/DataTable'

import {
  getObjectConflicts,
  getObjectProvenance,
  type ObjectProvenance,
  type ValueConflict,
} from '@elysium/shell-api/api'

/**
 * Why the golden record says what it says, where two sources disagreed.
 *
 * `core/mirror/survivorship.py` states the promise: "deleting losing
 * values destroys trust. A person asking why the golden record says
 * Leeds needs to see that the CRM said Hull and was outranked --
 * otherwise the answer is an assertion." The losing values have been
 * written to an append-only table since GOLD-6 and nothing could read
 * them back; this is the screen half of that.
 *
 * BESIDE THE LINEAGE AND NOT INSTEAD OF IT, because they answer two
 * halves of one question. "Where did this row come from" is one silo
 * for the whole object; "why does this FIELD say this" is per field,
 * and is the only per-field source attribution the system has.
 *
 * MOST OBJECTS HAVE NONE, and that is the healthy case -- a deployment
 * declaring no identity resolution never records one. An empty list
 * renders nothing rather than "no conflicts", which would put a
 * reassurance on every object page to describe the absence of a
 * feature most deployments do not use.
 */
function Disagreements({ conflicts }: { conflicts: ValueConflict[] }) {
  if (conflicts.length === 0) return null

  // A FILL IS NOT A DISAGREEMENT (R67a): the preferred source held the
  // object and nothing in this field, so a later one supplied it.
  // Shown, because "why does this field say this" otherwise names the
  // preferred source for a value it never held -- but not headed as a
  // dispute when nothing was disputed.
  const disputed = conflicts.some((conflict) => conflict.kind !== 'filled')
  // R60: a column only when some row has a track record, so a
  // deployment without one sees the table it always did.
  const tracked = conflicts.some((conflict) => conflict.track_record)

  return (
    <section className="object-detail__conflicts">
      <h3>{disputed ? 'Where the sources disagreed' : 'Where a value came from another source'}</h3>
      <DataTable className="conflicts">
        <thead>
          <tr>
            <th>Field</th>
            <th>Serving</th>
            <th>Outranked</th>
            {tracked && <th>When these two disagreed before</th>}
          </tr>
        </thead>
        <tbody>
          {conflicts.map((conflict, index) => (
            <tr key={`${conflict.field ?? conflict.kind}-${conflict.recorded_at ?? index}`}>
              <td>
                {/* A SECURITY CONFLICT NAMES NO FIELD, because what is
                    contested is the whole object -- which compartment
                    it belongs to, and therefore who may see it. Worth
                    reading differently from a disagreement about a
                    name. */}
                {conflict.field ?? 'Which compartment'}
              </td>
              <td>
                {conflict.readable ? (
                  <>
                    <span className="conflicts__value">{conflict.chosen ?? '—'}</span>{' '}
                    <span className="conflicts__source">from {conflict.chosen_source}</span>
                  </>
                ) : (
                  /* THE VERDICT IS SAFE AND THE VALUES ARE NOT, which
                     is the rule masked_comparison follows for a merge
                     candidate: a reader can be told two sources
                     disagreed about an email without being shown
                     either address. */
                  <span className="conflicts__source">from {conflict.chosen_source}</span>
                )}
              </td>
              <td>
                {conflict.kind === 'filled' ? (
                  <span className="conflicts__source">empty in {conflict.losing_source}</span>
                ) : conflict.readable ? (
                  <>
                    <span className="conflicts__value">{conflict.losing ?? '—'}</span>{' '}
                    <span className="conflicts__source">from {conflict.losing_source}</span>
                  </>
                ) : (
                  <span className="conflicts__source">from {conflict.losing_source}</span>
                )}
              </td>
              {tracked && (
                <td>
                  {/* EVIDENCE, NOT A VERDICT (R60): whose value both
                      sources ended up holding, rounded. It changes
                      nothing; the declared order still decides. */}
                  {conflict.track_record ? (
                    <span className="conflicts__source">
                      {conflict.track_record.source}'s value held about {conflict.track_record.about_percent}% of the
                      time
                    </span>
                  ) : (
                    <span className="conflicts__source">not enough history</span>
                  )}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </DataTable>
      {conflicts.some((conflict) => !conflict.readable) && (
        <p className="conflicts__withheld">
          Some values are not shown because you may not read those fields. The disagreement itself is.
        </p>
      )}
    </section>
  )
}

/**
 * Which source supplied each value (R38).
 *
 * THE OTHER HALF OF THE DISAGREEMENTS TABLE. That one says who LOST
 * where two sources disagreed; this says who supplied each value
 * whether or not anyone disagreed -- which is the question a fused
 * object otherwise answers wrongly, with one silo for every field.
 *
 * Rendered only for a fused type. A single-source type sends null, and
 * the silo above is already the answer for every field.
 */
function FieldSources({ sources }: { sources: Record<string, string> }) {
  const fields = Object.keys(sources).sort()
  if (fields.length === 0) return null
  return (
    <section className="object-detail__field-sources">
      <h3>Which source supplied each value</h3>
      <dl className="provenance">
        {fields.map((field) => (
          <div key={field} className="provenance__row">
            <dt>{field}</dt>
            <dd className="provenance__value">{sources[field]}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

export default function Provenance({ objectType, objectId }: { objectType: string; objectId: string }) {
  const [lineage, setLineage] = useState<ObjectProvenance | null>(null)
  const [conflicts, setConflicts] = useState<ValueConflict[]>([])

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

  // A SECOND FETCH RATHER THAN ONE ROUTE SERVING BOTH. They answer
  // different questions about different tables, and folding them
  // together would mean a deployment with no identity resolution --
  // most of them -- paying a scan of a table that does not exist on
  // every provenance read. Refused or unreachable renders nothing,
  // for the reason the lineage fetch above gives.
  useEffect(() => {
    let cancelled = false
    getObjectConflicts(objectType, objectId)
      .then((found) => {
        if (!cancelled) setConflicts(found)
      })
      .catch(() => {
        if (!cancelled) setConflicts([])
      })
    return () => {
      cancelled = true
    }
  }, [objectType, objectId])

  if (!lineage) {
    // THE DISAGREEMENTS STILL SHOW. They come from a different table
    // and a live-read deployment has no lineage at all, so making one
    // conditional on the other would hide the half that exists.
    return <Disagreements conflicts={conflicts} />
  }

  // A LIVE-READ DEPLOYMENT HAS NO LINEAGE AT ALL and the route answers
  // with every field absent rather than an error. Nothing to show is
  // nothing to show.
  // ON A FUSED TYPE THE SILO IS THE PRIMARY STORAGE'S, not every
  // field's -- the per-field list below is the answer for those -- so
  // the label says which it is.
  const fused = lineage.field_sources != null
  const rows = [
    [fused ? 'Primary silo' : 'Silo', lineage.silo],
    ['Source table', lineage.source_table],
    ['Bronze snapshot', lineage.bronze_snapshot_id],
    ['Row hash', lineage.row_hash],
  ].filter(([, value]) => value)

  if (rows.length === 0) return <Disagreements conflicts={conflicts} />

  return (
    <>
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
      {lineage.field_sources && <FieldSources sources={lineage.field_sources} />}
      <Disagreements conflicts={conflicts} />
    </>
  )
}
