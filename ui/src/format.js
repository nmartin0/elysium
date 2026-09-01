// format.js  (small, shared display-formatting helpers)
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
export function formatFieldName(name) {
  const spaced = name.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function formatValue(value) {
  if (value === null || value === undefined) return '(not set)'
  return String(value)
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
export function getDisplayTitle(typeSchema, fields, id) {
  const titleField = typeSchema?.title_field
  if (titleField && fields[titleField] !== null && fields[titleField] !== undefined) {
    return fields[titleField]
  }
  return id
}
