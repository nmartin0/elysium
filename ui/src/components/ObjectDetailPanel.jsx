import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getObjectDetail, ApiError } from '../api'
import { formatFieldName, formatValue } from '../format'

// Stage 2 of the Palantir-parity UI plan -- Object View. A real,
// dedicated page for one specific object: every field the caller can
// see, with LINK fields rendered as real, clickable navigation to
// another object's own Object View, not just a raw id string. Reached
// by clicking a result in ObjectSearchPanel (Stage 1), or any real,
// bookmarked/shared URL -- see App.jsx's own comment for why this
// specific screen is what justified adding real routing at all.
export default function ObjectDetailPanel({ visibleSchema, onSessionExpired }) {
  const { objectType, objectId } = useParams()
  const [fields, setFields] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  // Same stale-response guard as ObjectSearchPanel's own live search --
  // here it protects against rapid navigation between two DIFFERENT
  // objects on the SAME route pattern (React Router re-renders this
  // component in place with new params; it does not unmount/remount
  // it), where an earlier object's slower response could otherwise
  // overwrite a later object's already-correct one.
  const latestRequestId = useRef(0)

  useEffect(() => {
    const thisRequestId = ++latestRequestId.current
    setLoading(true)
    setError(null)
    // Cleared immediately, not left showing the PREVIOUS object's
    // fields while the new one loads -- a real correctness/clarity
    // concern, not just tidiness: briefly showing stale-but-genuinely-
    // real data for a different object during navigation would be
    // actively misleading, not merely an empty flash.
    setFields(null)

    async function loadDetail() {
      try {
        const response = await getObjectDetail(objectType, objectId)
        if (thisRequestId !== latestRequestId.current) return
        setFields(response.fields)
      } catch (err) {
        if (thisRequestId !== latestRequestId.current) return
        if (err instanceof ApiError && err.status === 401) {
          onSessionExpired()
          return
        }
        setError(err.message)
      } finally {
        if (thisRequestId === latestRequestId.current) setLoading(false)
      }
    }
    loadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objectType, objectId])

  const typeSchema = visibleSchema ? visibleSchema[objectType] : null

  function renderFieldValue(fieldName, value) {
    const fieldSchema = typeSchema?.fields?.[fieldName]
    const isLink = fieldSchema?.type === 'link'

    if (!isLink) return formatValue(value)
    if (value === null || value === undefined) return formatValue(value)

    const targetType = fieldSchema.target
    // cardinality "many" -> an array of linked ids; "one" -> a single
    // linked id -- get_object() (the real backend mechanism) already
    // resolves both shapes correctly; this only decides how to RENDER
    // whichever shape arrived.
    const linkedIds = Array.isArray(value) ? value : [value]
    if (linkedIds.length === 0) return formatValue(null)

    return (
      <span className="object-detail__links">
        {linkedIds.map((linkedId, index) => (
          <span key={linkedId}>
            {index > 0 && ', '}
            <Link to={`/objects/${targetType}/${encodeURIComponent(linkedId)}`}>{String(linkedId)}</Link>
          </span>
        ))}
      </span>
    )
  }

  if (loading) {
    return (
      <div className="object-detail">
        <p>Loading…</p>
      </div>
    )
  }

  if (error) {
    return (
      <div className="object-detail">
        <p className="error">{error}</p>
      </div>
    )
  }

  const hasAnyRealValue = fields && Object.values(fields).some((value) => value !== null && value !== undefined)

  if (!hasAnyRealValue) {
    // Deliberately generic -- matches api/routes.py's own "unknown
    // type and denied/nonexistent object look identical" design.
    // Never phrase this as "not found" specifically vs "access
    // denied" specifically; the backend itself doesn't distinguish
    // them, and this screen must not either.
    return (
      <div className="object-detail">
        <p>Nothing to show here.</p>
      </div>
    )
  }

  return (
    <div className="object-detail">
      <p className="object-detail__type">{objectType}</p>
      <h2 className="object-detail__id">{objectId}</h2>
      <dl className="object-detail__fields">
        {Object.entries(fields).map(([fieldName, value]) => (
          <div key={fieldName} className="object-detail__field">
            <dt>{formatFieldName(fieldName)}</dt>
            <dd>{renderFieldValue(fieldName, value)}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}

// =============================================================================
// AI-ONLY NOTES -- not user-facing. Context for a future AI session (or me,
// later) that lacks this conversation's history. Update this section
// whenever something genuinely open, deferred, or rejected comes up here.
// =============================================================================
//
// CONTEXT: Stage 2 of the Palantir-parity UI plan -- see api/
// routes.py's own AI-notes for the backend (GET /objects/{type}/{id}),
// and ObjectSearchPanel.jsx's own for Stage 1. Stage 3 (a real action-
// invocation button here, reusing PendingWriteCard as-is) remains
// planned, deliberately NOT attempted in this pass.
//
// SECURITY: this component NEVER tries to distinguish "this object
// doesn't exist" from "this object exists but you can't see it" --
// matches the backend's own deliberate design (every field null,
// identical shape, for both cases -- see api/routes.py's own
// docstring on get_object_detail_route). Do not "improve" this later
// into a more specific error message without re-reading that
// reasoning first; a more specific message here would leak exactly
// the thing the backend was deliberately built not to leak.
//
// The visibleSchema prop is used ONLY to decide how to RENDER a field
// (plain value vs clickable link) -- never to decide whether a value
// is shown at all. That decision is made entirely server-side, before
// this component ever sees a response; a field this schema doesn't
// even know about (a stale/mismatched visibleSchema, in theory) would
// still render correctly as a plain value via formatFieldName/
// formatValue's own fallback behavior, just without link treatment --
// never hidden, never fabricated.
//
// DEFERRED (known, intentional, not yet built):
// - No "return to where I was" breadcrumb/back trail across multiple
//   hops of link-following (Customer -> Transaction -> ...) beyond
//   the browser's own native back button, which already works
//   correctly given this is real routing now.
// - No loading skeleton matching the eventual field layout -- a plain
//   "Loading…" text, matching every other data-fetching component's
//   own existing convention in this app.
