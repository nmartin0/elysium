// format.ts  (small, shared display-formatting helpers)
//
// Extracted from PendingWriteCard.jsx once ObjectSearchPanel.jsx needed
// the SAME two functions -- one source of truth for "how a field name/
// value reads on screen," not two copies that could silently drift
// apart (e.g. one component learning to handle a new value type the
// other doesn't).

// "balance" stays "Balance"; "reopen_reason" becomes "Reopen reason"
// -- every real field name in this project's own schemas (balance,
// name, email, region, status, reopen_reason, subject, category, ...)
// reads correctly through this one, simple transformation. NOT
// Title Case for multi-word names -- the frontend-design skill's own
// guidance against needless ALL CAPS labels applies equally to
// needless Title Case; sentence case is the plainer, less templated
// choice.
export function formatFieldName(name: string): string {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

// unknown, not a narrower type -- every real caller (confirmed by
// reading every one directly, not assumed) passes a raw value straight
// from an untyped JSON API response (a field's own current value, an
// expected_current_value, a link array element after unwrapping) or a
// literal null -- honestly unknown at this boundary, not a lie this
// function's own signature should tell just because String() happens
// to accept anything.
export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '(not set)'
  return String(value)
}

// The shape of ONE object type's own entry within visibleSchema (the
// backend's GET /me/visible-schema response) that this function
// actually reads -- deliberately NOT a shared, exported type yet.
// Every other place in this codebase that touches visibleSchema needs
// more of its own shape (e.g. ObjectDetailPanel.jsx's own field.type/
// field.target for link rendering) -- a shared type covering the
// UNION of every caller's own needs, extracted before a second real
// caller exists to confirm it's actually the same shape, would be
// exactly the kind of speculative generality this project has
// consistently avoided elsewhere (see Shell.jsx's own AI-notes on why
// React Context was deliberately not introduced early). Revisit this
// once a second file's own type needs enough overlap to justify one.
interface TitleFieldSchema {
  // string | null | undefined, not just string | undefined -- a real
  // correction caught while converting this file's own test suite,
  // not assumed: the backend's own visible_schema() genuinely returns
  // title_field as null (never omits the key, never the field name
  // itself) the moment a caller can't actually read that field -- see
  // this function's own comment below, and core/ontology/mediator.
  // py's docstring on visible_schema() for the real, server-side
  // behavior this mirrors.
  title_field?: string | null
}

// Given a type's own visibleSchema entry (or undefined/null if it
// hasn't loaded yet, or the type has none), a real object's own
// fields dict, and its raw id -- returns whichever should stand in as
// the object's real, human-readable label. Falls back to the raw id
// whenever there's genuinely nothing better to show: no title_field
// declared for this type at all, OR the caller can't actually see
// that field's own value (visible_schema() itself already resolves
// THAT distinction server-side -- title_field comes back null there,
// never the field's own name, the moment a caller lacks the matching
// read: grant -- see core/ontology/mediator.py's own docstring on
// visible_schema()). This function never makes its own permission
// decision; it only ever reads what the backend already decided.
export function getDisplayTitle(
  typeSchema: TitleFieldSchema | null | undefined,
  fields: Record<string, unknown>,
  id: string,
): unknown {
  const titleField = typeSchema?.title_field
  if (titleField && fields[titleField] !== null && fields[titleField] !== undefined) {
    return fields[titleField]
  }
  return id
}

/**
 * A timestamp as a person reads it.
 *
 * Relative within 24 hours, short absolute after -- which is the
 * convention the platform we model uses: "applications will only
 * format in relative terms up to 24 hours ago. After this, it will
 * render in Date and time (short) form with the day of the week".
 *
 * The hybrid is better than either alone. "3 hours ago" is what you
 * want for something that happened during your shift; "Wed, 22 Jul
 * 2026, 13:00" is what you want for anything older, because "47 days
 * ago" is a number nobody can place.
 *
 * NOT FOR AUDIT DATA. An audit trail is read to answer "was this
 * before or after X", and the same source is explicit that audit logs
 * carry "precise timestamps for temporal analysis". History keeps its
 * raw ISO; this is for human content.
 */
export function formatTimestamp(iso: string, now: Date = new Date()): string {
  const then = new Date(iso)
  if (Number.isNaN(then.getTime())) return iso

  const seconds = Math.floor((now.getTime() - then.getTime()) / 1000)

  // Future timestamps fall through to absolute. Clock skew between a
  // server and a browser makes "in 3 seconds" a real thing to render,
  // and it reads as a bug rather than as skew.
  if (seconds >= 0 && seconds < 86400) {
    if (seconds < 60) return 'just now'
    const minutes = Math.floor(seconds / 60)
    if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`
    const hours = Math.floor(minutes / 60)
    return `${hours} hour${hours === 1 ? '' : 's'} ago`
  }

  return then.toLocaleString(undefined, {
    weekday: 'short',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
