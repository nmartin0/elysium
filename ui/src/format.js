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
