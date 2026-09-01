import { useEffect, useRef, useState } from 'react'
import { getMyVisibleSchema, searchObjects, ApiError } from '../api'
import { formatFieldName, formatValue } from '../format'

// The human-facing browse/search screen -- Palantir's own Object
// Explorer is the closest real-world analog (a real research +
// architecture conversation with the user), scaled down to a fixed,
// hand-built screen rather than a generic app-building tool: pick a
// type, search across it (or browse everything, nothing typed yet),
// see real field values per result. No object detail page or direct
// action invocation yet -- both are later, planned pieces building on
// top of this one, not attempted here.
//
// SEARCH IS LIVE, deliberately, not a submit-driven form like Query
// Panel's own pattern -- a real, deliberate departure from this
// project's existing convention, chosen specifically for THIS
// screen's own stated audience (a non-technical end user who
// shouldn't need to remember to press a button to see results as
// they narrow down what they're looking for). Debounced (300ms) to
// avoid a real request on every single keystroke.
const DEBOUNCE_MS = 300

export default function ObjectSearchPanel({ onSessionExpired }) {
  const [objectTypes, setObjectTypes] = useState(null)
  const [selectedType, setSelectedType] = useState(null)
  const [queryText, setQueryText] = useState('')
  const [results, setResults] = useState([])
  const [totalMatches, setTotalMatches] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Guards against a slower, EARLIER request's response overwriting a
  // faster, LATER one's already-correct results -- a real, well-known
  // race with live/debounced search, not a hypothetical: two
  // in-flight requests can resolve in either order over a real
  // network. Only the response matching the MOST RECENT request is
  // ever applied.
  const latestRequestId = useRef(0)

  useEffect(() => {
    async function loadObjectTypes() {
      try {
        const schema = await getMyVisibleSchema()
        const types = Object.keys(schema)
        setObjectTypes(types)
        if (types.length > 0) setSelectedType(types[0])
      } catch (err) {
        if (err instanceof ApiError && err.status === 401) {
          onSessionExpired()
          return
        }
        setError(err.message)
      }
    }
    loadObjectTypes()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (!selectedType) return

    const thisRequestId = ++latestRequestId.current
    setLoading(true)
    setError(null)

    const timeoutId = setTimeout(async () => {
      try {
        const response = await searchObjects(selectedType, queryText)
        if (thisRequestId !== latestRequestId.current) return
        setResults(response.results)
        setTotalMatches(response.total_matches)
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
    }, DEBOUNCE_MS)

    return () => clearTimeout(timeoutId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, queryText])

  if (objectTypes === null) {
    return <div className="object-search">{error ? <p className="error">{error}</p> : <p>Loading…</p>}</div>
  }

  if (objectTypes.length === 0) {
    return (
      <div className="object-search">
        <p>Nothing available to search yet.</p>
      </div>
    )
  }

  return (
    <div className="object-search">
      <div className="object-search__controls">
        <select value={selectedType} onChange={(event) => setSelectedType(event.target.value)}>
          {objectTypes.map((type) => (
            <option key={type} value={type}>
              {type}
            </option>
          ))}
        </select>
        <input
          type="text"
          value={queryText}
          onChange={(event) => setQueryText(event.target.value)}
          placeholder={`Search ${selectedType}…`}
        />
      </div>

      {error && <p className="error">{error}</p>}
      {loading && <p className="object-search__status">Searching…</p>}

      {!loading && results.length === 0 && !error && <p className="object-search__empty">No results.</p>}

      <ul className="object-search__results">
        {results.map((result) => (
          <li key={result.id} className="object-search__result">
            <p className="object-search__result-id">{result.id}</p>
            <dl className="object-search__result-fields">
              {Object.entries(result.fields).map(([field, value]) => (
                <div key={field} className="object-search__result-field">
                  <dt>{formatFieldName(field)}</dt>
                  <dd>{formatValue(value)}</dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>

      {totalMatches > results.length && (
        <p className="object-search__more">
          Showing {results.length} of {totalMatches} matches -- narrow your search to see more.
        </p>
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
// CONTEXT: the first real screen for a genuine, staged architecture
// direction (Palantir's own Object Explorer/Object View/Actions
// widgets as the real-world reference, scaled to fixed, hand-built
// screens rather than a generic app-building tool -- see api/
// routes.py's own AI-notes for the backend side, core/ontology/
// mediator.py's for search_object_free_text()). This is Stage 1 only
// -- browse/search. Stage 2 (a real per-object detail page, an Object
// View equivalent) and Stage 3 (direct action invocation from that
// page, reusing PendingWriteCard as-is) are both planned, deliberately
// NOT attempted here.
//
// RESOLVED (kept for history):
// - Building this surfaced a real, missing backend prerequisite:
//   nothing let an ordinary end user ask "which object types exist
//   for ME" -- api/routes.py's new GET /me/visible-schema closes that
//   (see that file's own AI-notes).
// - Verified with more than "it builds": the exact real /objects/
//   {type}/search response shape (confirmed against tests/
//   integration/test_api.py's own real HTTP test) was fed through
//   react-dom/server and actually looked at, twice -- the first pass
//   caught a real, honest visual issue (the type dropdown looked
//   cramped next to the search box for a short type name), fixed via
//   a min-width, then re-rendered and re-checked before trusting it.
//
// DEFERRED (known, intentional, not yet built):
// - Live, debounced search (300ms) is a deliberate departure from
//   this app's existing submit-driven pattern (QueryPanel's own
//   form), chosen specifically for this screen's OWN stated audience
//   (a non-technical end user who shouldn't need to remember to press
//   a button) -- not applied retroactively to QueryPanel, which has
//   its own, different reason to stay submit-driven (a real, possibly
//   slow LLM call per submission, not a cheap live search).
// - No real routing yet (see App.jsx's own comment) -- a plain state
//   toggle is still fine for THIS screen (nothing about "which type,
//   what I typed" needs to survive a reload or be shareable), but
//   will genuinely need to change once Stage 2's Object View needs a
//   real, bookmarkable URL per object.
// - No "title field" concept exists in the schema yet -- each result
//   is labeled by its raw id (e.g. "cust_001"), not a human-chosen
//   display name. Palantir's own Object Explorer has this (a
//   configurable "title property" per object type); worth adding to
//   ontology_schema.yaml's own format if this ever feels like a real
//   gap in practice, not invented speculatively here.
// - No pagination -- MAX_SEARCH_RESULTS (api/routes.py, 50) is a hard
//   safety cap; a query matching more than that shows a "narrow your
//   search" hint, not a way to see the rest.
