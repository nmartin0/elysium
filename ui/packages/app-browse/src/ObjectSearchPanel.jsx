import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { searchObjects, handleIfSessionExpired } from '@elysium/shell-api/api'
import { formatFieldName, formatValue, getDisplayTitle } from '@elysium/shell-api/format'

// The human-facing browse/search screen -- Palantir's own Object
// Explorer is the closest real-world analog (a real research +
// architecture conversation with the user), scaled down to a fixed,
// hand-built screen rather than a generic app-building tool: pick a
// type, search across it (or browse everything, nothing typed yet),
// see real field values per result, click through to a real per-
// object detail page (Stage 2 -- see ObjectDetailPanel.jsx).
//
// SEARCH IS LIVE, deliberately, not a submit-driven form like Query
// Panel's own pattern -- a real, deliberate departure from this
// project's existing convention, chosen specifically for THIS
// screen's own stated audience (a non-technical end user who
// shouldn't need to remember to press a button to see results as
// they narrow down what they're looking for). Debounced (300ms) to
// avoid a real request on every single keystroke.
const DEBOUNCE_MS = 300

export default function ObjectSearchPanel({ visibleSchema, onSessionExpired }) {
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

  const objectTypes = visibleSchema ? Object.keys(visibleSchema) : null

  useEffect(() => {
    if (selectedType === null && objectTypes && objectTypes.length > 0) {
      setSelectedType(objectTypes[0])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objectTypes])

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
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(err.message)
      } finally {
        if (thisRequestId === latestRequestId.current) setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timeoutId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, queryText])

  if (objectTypes === null) {
    return (
      <div className="object-search">
        <p>Loading…</p>
      </div>
    )
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
        <select
          value={selectedType ?? objectTypes[0]}
          onChange={(event) => setSelectedType(event.target.value)}
        >
          {/* selectedType itself still starts as null -- the effect
              below sets it to a real value once objectTypes is known,
              and the search effect further down correctly waits for
              that real value before firing (gated on `if
              (!selectedType) return`). This fallback exists ONLY so
              the <select> element's own displayed value is never
              null during that brief window -- a real, previously-
              present React warning ("a component is changing an
              uncontrolled input to be controlled"), not a
              hypothetical one. By the time this element renders at
              all, objectTypes is already confirmed non-null and non-
              empty (see the two early returns above), so
              objectTypes[0] is always safe here. */}
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
        {results.map((result) => {
          const titleValue = getDisplayTitle(visibleSchema?.[selectedType], result.fields, result.id)
          return (
            <li key={result.id} className="object-search__result">
              <Link
                to={`/objects/${selectedType}/${encodeURIComponent(result.id)}`}
                className="object-search__link"
              >
                <p className="object-search__result-title">{titleValue}</p>
                {titleValue !== result.id && <p className="object-search__result-subtitle">{result.id}</p>}
                <dl className="object-search__result-fields">
                  {Object.entries(result.fields).map(([field, value]) => (
                    <div key={field} className="object-search__result-field">
                      <dt>{formatFieldName(field)}</dt>
                      <dd>{formatValue(value)}</dd>
                    </div>
                  ))}
                </dl>
              </Link>
            </li>
          )
        })}
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
// mediator.py's for search_object_free_text()). Stage 3 (direct
// action invocation from ObjectDetailPanel) was built later the same
// session -- see ActionForm.jsx's own docstring.
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
// - Stage 2: this component no longer fetches its own /me/visible-
//   schema -- lifted to App.jsx (fetched once, passed down as a
//   prop), since ObjectDetailPanel needs the exact same value.
//   Considered React Context as the alternative, deliberately not
//   used -- this app's tree is still shallow/flat (App -> a handful
//   of sibling views), exactly the case Context is usually overkill
//   for; worth revisiting if the tree ever grows deeper.
// - Results are now real react-router-dom <Link>s to /objects/{type}/
//   {id} (Stage 2's Object View), not inert rows.
// - title_field was later added to the schema (see core/ontology/
//   object_type_validation.py) -- getDisplayTitle() above (shared, in
//   ../format) uses it when a type declares one and the caller can
//   actually see that field's own value, falling back to the raw id
//   otherwise. Matches Palantir's own Object Explorer, which has the
//   equivalent concept ("title key").
// - A real, pre-existing React warning ("a component is changing an
//   uncontrolled input to be controlled") is fixed -- the <select>'s
//   own value fell back to objectTypes[0] at render time instead of
//   ever displaying selectedType while it's still null (the brief
//   window before the effect below catches up and sets a real value).
//   Confirmed genuinely fixed, not just silenced: ran the real, live
//   Vite dev server (React's own dev-mode console warnings are
//   stripped from production builds, so this specifically needed dev
//   mode, not the production build most other live checks in this
//   project use), logged in, navigated to this exact screen, and
//   captured the full browser console -- zero React warnings of any
//   kind, confirmed directly rather than assumed from the code change
//   alone.
//
// DEFERRED (known, intentional, not yet built):
// - Live, debounced search (300ms) is a deliberate departure from
//   this app's existing submit-driven pattern (QueryPanel's own
//   form), chosen specifically for this screen's OWN stated audience
//   (a non-technical end user who shouldn't need to remember to press
//   a button) -- not applied retroactively to QueryPanel, which has
//   its own, different reason to stay submit-driven (a real, possibly
//   slow LLM call per submission, not a cheap live search).
// - No pagination -- MAX_SEARCH_RESULTS (api/routes.py, 50) is a hard
//   safety cap; a query matching more than that shows a "narrow your
//   search" hint, not a way to see the rest.
