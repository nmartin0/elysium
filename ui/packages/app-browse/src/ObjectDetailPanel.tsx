import { useEffect, useRef, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { getObjectDetail, getVisibleActionTypes, getErrorMessage, handleIfSessionExpired } from '@elysium/shell-api/api'
import { formatFieldName, formatValue, getDisplayTitle } from '@elysium/shell-api/format'
import ActionForm, { type ActionDef } from './ActionForm'

// The real shape of ONE object type's own entry within the backend's
// visible-schema response (GET /me/visible-schema, GET /users/{u}/
// visible-schema). Exported here, not kept local -- unlike format.
// ts's own deliberately-local TitleFieldSchema (a strict SUBSET of
// this same shape, still structurally compatible with it), this
// component is the first to need MORE of it (fields, for link
// rendering below), and ObjectSearchPanel.jsx -- a KNOWN, not
// speculative, future consumer, since it receives the exact same
// visibleSchema prop and reads it the same way -- will need this
// full shape too once converted.
export interface FieldSchema {
  type: string
  target?: string
}

export interface TypeSchema {
  title_field?: string | null
  fields?: Record<string, FieldSchema>
}

export type VisibleSchema = Record<string, TypeSchema>

interface ObjectDetailPanelProps {
  visibleSchema: VisibleSchema | null
  onSessionExpired: () => void
}

// Stage 2 of the Palantir-parity UI plan -- Object View. A real,
// dedicated page for one specific object: every field the caller can
// see, with LINK fields rendered as real, clickable navigation to
// another object's own Object View, not just a raw id string. Reached
// by clicking a result in ObjectSearchPanel (Stage 1), or any real,
// bookmarked/shared URL -- see App.jsx's own comment for why this
// specific screen is what justified adding real routing at all.
// Stage 3 adds direct action invocation from this same page -- see
// ActionForm.jsx's own docstring.
export default function ObjectDetailPanel({ visibleSchema, onSessionExpired }: ObjectDetailPanelProps) {
  // useParams() itself types every param as string | undefined
  // regardless of the generic passed -- react-router-dom's own type
  // definition, since it can't statically know a given route
  // pattern's own params are always present. Genuinely guaranteed
  // here, not assumed: this component only ever renders under
  // /objects/:objectType/:objectId, a route pattern where both
  // segments are required, never optional.
  const params = useParams<{ objectType: string; objectId: string }>()
  const objectType = params.objectType!
  const objectId = params.objectId!
  const [fields, setFields] = useState<Record<string, unknown> | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [visibleActionTypes, setVisibleActionTypes] = useState<Record<string, ActionDef> | null>(null)
  const [activeAction, setActiveAction] = useState<string | null>(null)

  // Same stale-response guard as ObjectSearchPanel's own live search --
  // here it protects against rapid navigation between two DIFFERENT
  // objects on the SAME route pattern (React Router re-renders this
  // component in place with new params; it does not unmount/remount
  // it), where an earlier object's slower response could otherwise
  // overwrite a later object's already-correct one.
  const latestRequestId = useRef(0)

  async function loadDetail() {
    const thisRequestId = ++latestRequestId.current
    setLoading(true)
    setError(null)
    // Cleared immediately, not left showing the PREVIOUS object's
    // fields while the new one loads -- a real correctness/clarity
    // concern, not just tidiness: briefly showing stale-but-genuinely-
    // real data for a different object during navigation would be
    // actively misleading, not merely an empty flash.
    setFields(null)

    try {
      // getObjectDetail() itself returns Promise<unknown> (see api.ts's
      // own header comment on why) -- asserted to the real, known
      // success shape here, matching api/routes.py's own documented
      // contract for get_object_detail_route.
      const response = (await getObjectDetail(objectType, objectId)) as { fields: Record<string, unknown> }
      if (thisRequestId !== latestRequestId.current) return
      setFields(response.fields)
    } catch (err) {
      if (thisRequestId !== latestRequestId.current) return
      if (handleIfSessionExpired(err, onSessionExpired)) return
      setError(getErrorMessage(err))
    } finally {
      if (thisRequestId === latestRequestId.current) setLoading(false)
    }
  }

  useEffect(() => {
    loadDetail()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objectType, objectId])

  // Fetched ONCE per mount, not re-fetched on every object navigation
  // within this same route pattern -- which actions a user can invoke
  // at all doesn't depend on which specific object they're currently
  // looking at, only on their own role's grants.
  useEffect(() => {
    async function loadActionTypes() {
      try {
        // Asserted to the real, known success shape, same reasoning
        // as loadDetail()'s own response above.
        const response = (await getVisibleActionTypes()) as Record<string, ActionDef>
        setVisibleActionTypes(response)
      } catch (err) {
        if (handleIfSessionExpired(err, onSessionExpired)) return
        // Deliberately silent otherwise -- a real failure here means
        // no action buttons render at all, which is a safe, honest
        // degradation (never fabricating a button for an action that
        // might not really be available), not a broken page; the
        // object's own fields above are unaffected either way.
      }
    }
    loadActionTypes()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const typeSchema = visibleSchema ? visibleSchema[objectType] : null

  function renderFieldValue(fieldName: string, value: unknown): React.ReactNode {
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
          <span key={String(linkedId)}>
            {index > 0 && ', '}
            <Link to={`/objects/${targetType}/${encodeURIComponent(String(linkedId))}`}>{String(linkedId)}</Link>
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

  const availableActions = Object.entries(visibleActionTypes ?? {}).filter(
    ([, actionDef]) => actionDef.affected_object_types.includes(objectType) && actionDef.executable,
  )

  const titleValue = getDisplayTitle(typeSchema, fields, objectId)

  return (
    <div className="object-detail">
      <p className="object-detail__type">{objectType}</p>
      <h2 className="object-detail__title">{titleValue as React.ReactNode}</h2>
      {titleValue !== objectId && <p className="object-detail__subtitle">{objectId}</p>}
      <dl className="object-detail__fields">
        {Object.entries(fields).map(([fieldName, value]) => (
          <div key={fieldName} className="object-detail__field">
            <dt>{formatFieldName(fieldName)}</dt>
            <dd>{renderFieldValue(fieldName, value)}</dd>
          </div>
        ))}
      </dl>

      {availableActions.length > 0 && !activeAction && (
        <div className="object-detail__actions">
          {availableActions.map(([actionName]) => (
            <button key={actionName} className="secondary" onClick={() => setActiveAction(actionName)}>
              {actionName}
            </button>
          ))}
        </div>
      )}

      {activeAction && (
        <ActionForm
          actionName={activeAction}
          // visibleActionTypes![activeAction]! -- genuinely safe by
          // construction, not assumed: activeAction only ever gets
          // set (above) from availableActions' own entries, which are
          // themselves derived from visibleActionTypes -- a non-empty
          // availableActions therefore guarantees BOTH that
          // visibleActionTypes is non-null AND that this specific key
          // exists in it, even though these are separate state/
          // derived values TypeScript can't itself connect.
          actionDef={visibleActionTypes![activeAction]!}
          objectType={objectType}
          objectId={objectId}
          onCancel={() => setActiveAction(null)}
          onResolved={() => {
            setActiveAction(null)
            loadDetail()
          }}
          onSessionExpired={onSessionExpired}
        />
      )}
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
// and ObjectSearchPanel.jsx's own for Stage 1. Stage 3 (direct action
// invocation from this page) is now built too -- see ActionForm.jsx's
// own docstring for that piece; this file only owns discovering which
// actions are available for the current object type and refreshing
// its own fields once one has actually been applied or rejected
// (loadDetail() extracted to a standalone function specifically so
// onResolved below could call it again, not just on mount/navigation).
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
// availableActions filters on affected_object_types AND executable
// locally, in this component -- NOT a second, server-side filter. The
// real, only authorization decisions (can this user even SEE this
// action; can this user genuinely INVOKE it) already happened inside
// GET /me/visible-action-types itself -- executable is computed
// there, per action, specifically so a discover:action_types-holding
// role (which sees actions it cannot invoke -- see that grant's own
// docstring on WriteMediator.visible_action_types()) never gets shown
// a button for one of them. Deliberately HIDDEN, not shown disabled --
// decided explicitly with the user after checking both Palantir's own
// real Object View convention (which supports either, but frames
// disable as for a condition the user could fix by changing form
// input) and the general, converging UX consensus for permission-
// based unavailability specifically: hide, since no amount of correct
// form-filling grants a permission the user doesn't hold. This
// filter is purely "which of the ones I'm already allowed to see AND
// invoke make sense to offer HERE," a display decision built on TWO
// already-real, server-computed authorization facts, not a new
// security decision of its own.
//
// FieldSchema/TypeSchema/VisibleSchema -- the shared prop-type shape
// for the whole visible-schema response -- exported from THIS file
// (see this file's own top-of-file comment for why here) once the
// TypeScript migration reached this component.
//
// DEFERRED (known, intentional, not yet built):
// - No "return to where I was" breadcrumb/back trail across multiple
//   hops of link-following (Customer -> Transaction -> ...) beyond
//   the browser's own native back button, which already works
//   correctly given this is real routing now.
// - No loading skeleton matching the eventual field layout -- a plain
//   "Loading…" text, matching every other data-fetching component's
//   own existing convention in this app.
// - visibleActionTypes is fetched independently here, NOT lifted to
//   App.jsx the way visibleSchema was -- deliberately, not an
//   oversight: only this component needs it today, unlike
//   visibleSchema (needed by both this file and ObjectSearchPanel.jsx
//   at the time of that lift). Revisit the same lift if a second
//   consumer (e.g. quick action buttons on search results) ever
//   needs it too.
