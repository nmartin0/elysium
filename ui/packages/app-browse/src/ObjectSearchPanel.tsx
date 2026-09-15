import { Fragment, useEffect, useState } from 'react'
import { Button, Card, CardList, Checkbox, HTMLSelect, NonIdealState } from '@blueprintjs/core'
import { Link } from 'react-router-dom'
import {
  getDataFreshness,
  getErrorMessage,
  getVisibleActionTypesCached,
  handleIfSessionExpired,
  matchingIds,
  searchObjects,
  type DataFreshness,
} from '@elysium/shell-api/api'
import FilterBar, { type FieldFilter } from '@elysium/shell-api/components/FilterBar'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import LoadingState from '@elysium/shell-api/components/LoadingState'
import ViewSelector, { type ViewOption } from '@elysium/shell-api/components/ViewSelector'
import Workspace, { WorkspaceFilter } from '@elysium/shell-api/components/Workspace'
import { useClearUrlKeys, useUrlJson, useUrlValue } from '@elysium/shell-api/useUrlState'

import ActiveFilters from './ActiveFilters'
import BulkActionForm from './BulkActionForm'
import BulkActionsMenu, { type BulkAction } from './BulkActionsMenu'
import SavedViews from './SavedViews'
import SelectionBar from './SelectionBar'
import { formatFieldName, formatTimestamp, formatValue, getDisplayTitle } from '@elysium/shell-api/format'
import type { SubAppProps } from '@elysium/shell-api/types'
import { useLatestRequestGuard } from '@elysium/shell-api/useLatestRequestGuard'
import type { VisibleSchema } from '@elysium/shell-api/types'
import { readPreference, writePreference } from '@elysium/shell-api/browserPreferences'

import { asConditions, type ChartFilter } from './aggregateCharts'
import ChartsPanel from './ChartsPanel'

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

export interface SearchResult {
  id: string
  fields: Record<string, unknown>
}

// visibleSchema is real, additional data this route needs beyond the
// shell's own base contract -- extends SubAppProps rather than
// redeclaring onSessionExpired independently. See SubAppProps's own
// header comment for the full reasoning.
interface ObjectSearchPanelProps extends SubAppProps {
  visibleSchema: VisibleSchema | null
  /** Whose column choices to read. Browser storage is per-machine, so
   *  without this a second user inherits the first's. */
  username: string
}

const BROWSE_VIEWS: readonly ViewOption[] = [
  { id: 'table', label: 'Table', icon: 'th' },
  { id: 'charts', label: 'Charts', icon: 'chart' },
]

export default function ObjectSearchPanel({ visibleSchema, username, onSessionExpired }: ObjectSearchPanelProps) {
  // THE VIEW LIVES IN THE URL, so it can be shared, bookmarked and
  // found again in history. The object type, the search text, the
  // sort and the chart filters are a property of the QUESTION rather
  // than of the person asking it.
  //
  // Column choices deliberately do NOT move -- those are a preference,
  // they follow a user across every view, and a shared link that
  // changed the recipient's columns would be a surprise rather than a
  // convenience. See useUrlState.ts for the full split.
  const [urlType, setUrlType] = useUrlValue('type', '')
  const selectedType = urlType === '' ? null : urlType
  const setSelectedType = (next: string | null) => setUrlType(next ?? '')
  const [queryText, setQueryText] = useUrlValue('q', '')
  const [results, setResults] = useState<SearchResult[]>([])
  // Page tokens are OPAQUE and kept as a stack, so Back returns to the
  // exact page you came from. Reconstructing a previous token by
  // arithmetic would assume an encoding the server does not promise.
  const [pageToken, setPageToken] = useState<string | null>(null)
  const [previousTokens, setPreviousTokens] = useState<string[]>([])
  const [nextPageToken, setNextPageToken] = useState<string | null>(null)
  const [orderBy, setOrderBy] = useUrlValue('sort', '')
  const clearUrlKeys = useClearUrlKeys()
  // Per type, so switching types does not carry one type's chosen
  // columns onto another where those field names mean nothing.
  //
  // PERSISTED, because this route unmounts: opening a result and
  // coming back reset the choice silently. Found by using it, not by a
  // test -- the tests checked per-type isolation and never navigated
  // away.
  const [chosenColumns, setChosenColumnsState] = useState<Record<string, string[]>>(() =>
    readPreference('browseColumns', username, {}),
  )

  /**
   * A clicked chart value, toggled into the filter.
   *
   * KEEP on first click, and clicking the same value again removes it
   * -- so a click is always undoable by repeating it, which is what
   * makes exploring by clicking safe.
   */
  function removeCrossFilter(field: string) {
    setCrossFilter((current) => current.filter((entry) => entry.field !== field))
  }

  function toggleChartValue(field: string, value: string) {
    setCrossFilter((current) => {
      const existing = current.find((entry) => entry.field === field)
      if (existing === undefined) {
        return [...current, { field, values: [value], mode: 'keep' }]
      }
      const values = existing.values.includes(value)
        ? existing.values.filter((existingValue: string) => existingValue !== value)
        : [...existing.values, value]
      // A filter with nothing left in it is no filter, not an empty
      // one -- `in []` would mean "match nothing".
      const rest = current.filter((entry) => entry.field !== field)
      return values.length === 0 ? rest : [...rest, { ...existing, values }]
    })
    setPageToken(null)
  }

  function setChosenColumns(next: Record<string, string[]>) {
    setChosenColumnsState(next)
    writePreference('browseColumns', username, next)
  }
  const [totalMatches, setTotalMatches] = useState(0)

  // WHICH OBJECTS AN ACTION WOULD APPLY TO, by id rather than by row,
  // so a selection survives paging and re-sorting. Foundry's rule:
  // "when results span multiple pages, selecting the header checkbox
  // selects all objects matching the applied filters, not just the
  // objects on the current page".
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set())

  // WHICH ACTIONS EXIST, for the bulk menu. Cached at the shell level,
  // so several panels asking costs one request.
  const [actionTypes, setActionTypes] = useState<BulkAction[]>([])
  const [bulkAction, setBulkAction] = useState<BulkAction | null>(null)
  const [selectingAll, setSelectingAll] = useState(false)

  useEffect(() => {
    void (getVisibleActionTypesCached() as Promise<Record<string, Omit<BulkAction, 'name'>>>)
      // A DICT KEYED BY NAME, not an array -- the route's response
      // model is dict[str, VisibleActionTypeResponse], and an entry
      // does NOT carry its own name. Calling .filter() on it threw and
      // blanked the whole page.
      //
      // My tests mocked it as an array, so they never saw the real
      // shape; ObjectDetailPanel.tsx already casts it correctly and I
      // did not look. Found by running the product.
      .then((byName) => setActionTypes(Object.entries(byName ?? {}).map(([name, spec]) => ({ ...spec, name }))))
      // SILENT ON FAILURE, and the menu simply does not appear. An
      // error banner about actions would be noise on a page whose job
      // is showing objects, and the actions are an addition to it
      // rather than the point of it.
      .catch(() => {})
  }, [])

  function toggleSelected(id: string) {
    setSelectedIds((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }
  /**
   * The cross-filter: one set of conditions driving the table AND
   * every chart.
   *
   * Kept here rather than in either half because both describe the
   * SAME object set -- charts over a different set than the table
   * beside them would be actively misleading. It ANDs with the text
   * query rather than replacing it, so narrowing by a chart click
   * narrows within a search rather than discarding it.
   */
  // JSON-encoded: a list of {field, value} pairs has no natural flat
  // query-string form, and inventing one would mean writing a parser
  // for it. A malformed value falls back to no filter rather than
  // throwing -- see useUrlJson.
  const [crossFilter, setCrossFilter] = useUrlJson<ChartFilter[]>('filters', [])

  // Whether the user narrowed anything, which is what separates "your
  // filters matched nothing" from "there is nothing here". Text search
  // and chart cross-filters both count: either one can empty a result
  // set that would otherwise have rows.
  const hasFilters = queryText.trim() !== '' || crossFilter.length > 0

  // Fetched once for the panel, not per search: freshness is a
  // deployment-wide fact and does not change between queries. A
  // failure is swallowed to null -- the indicator is worth having and
  // is not worth failing a search over, which is the same call
  // PendingWriteCard already makes.
  const [freshness, setFreshness] = useState<DataFreshness | null>(null)
  useEffect(() => {
    getDataFreshness()
      .then(setFreshness)
      .catch(() => setFreshness(null))
  }, [])

  const clearAllFilters = () => {
    // ONE navigation, not two. Each URL setter navigates rather than
    // queueing, so calling both in sequence made the second discard
    // the first and only half the filters cleared.
    clearUrlKeys(['q', 'filters'])
  }
  /**
   * Filters built in the filter bar, kept SEPARATE from the chart
   * cross-filter and combined only when a query is sent.
   *
   * Two sources, one object set. Merging them into one list would mean
   * clicking a chart could silently remove a filter someone typed, and
   * removing a typed filter could clear a chart selection -- each
   * would be editing the other's state.
   */
  const [barFilters, setBarFilters] = useState<FieldFilter[]>([])
  // WHICH TAB, because a link to a chart should open the chart. It is
  // part of what someone means by "look at this".
  const [view, setView] = useUrlValue('view', 'table')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Guards against a slower, EARLIER request's response overwriting a
  // faster, LATER one's already-correct results -- a real, well-known
  // race with live/debounced search, not a hypothetical: two
  // in-flight requests can resolve in either order over a real
  // network. Only the response matching the MOST RECENT request is
  // ever applied. Extracted, shared logic (see useLatestRequestGuard's
  // own header comment for the full story) -- ObjectDetailPanel.tsx
  // uses the exact same one, for its own, different, real reason.
  const { startRequest, isStale } = useLatestRequestGuard()

  const objectTypes = visibleSchema ? Object.keys(visibleSchema) : null

  // Sortable fields come from the caller's OWN visible schema, so one
  // they cannot read is never offered. That is not the security
  // boundary -- the server rejects an unreadable order_by regardless --
  // but offering a control that always fails is its own kind of wrong.
  //
  // Link fields are excluded: ordering by a relationship has no
  // meaning, and there is no column for the server to sort on.
  /**
   * Which fields a result card shows.
   *
   * Defaults to the PROMINENT ones the ontology author declared --
   * that metadata exists precisely so a screen does not have to guess
   * what matters about a type. Falling back to everything when none
   * are declared, because a card showing nothing is worse than one
   * showing too much.
   *
   * `visibility: hidden` is COSMETIC and documented as such: the field
   * is still in the response and a caller can still read it. Excluding
   * it here is a default, not a denial, and the picker below can turn
   * it back on.
   */
  const visibleColumns = (returned: string[]): string[] => {
    if (!selectedType) return returned
    const chosen = chosenColumns[selectedType]
    if (chosen) return returned.filter((field) => chosen.includes(field))
    const schemaFields = visibleSchema?.[selectedType]?.fields ?? {}
    const prominent = returned.filter((field) => schemaFields[field]?.visibility === 'prominent')
    if (prominent.length > 0) return prominent
    return returned.filter((field) => schemaFields[field]?.visibility !== 'hidden')
  }

  const sortableFields =
    selectedType && visibleSchema
      ? Object.entries(visibleSchema[selectedType]?.fields ?? {})
          .filter(([, field]) => field.type !== 'link')
          .map(([name, field]) => ({ name, label: field.display_name ?? name }))
      : []

  useEffect(() => {
    if (selectedType === null && objectTypes && objectTypes.length > 0) {
      setSelectedType(objectTypes[0]!)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [objectTypes])

  useEffect(() => {
    if (!selectedType) return

    const thisRequestId = startRequest()
    setLoading(true)
    setError(null)

    const timeoutId = setTimeout(async () => {
      try {
        // searchObjects() itself returns Promise<unknown> (see api.ts's
        // own header comment on why) -- asserted to the real, known
        // success shape here, matching api/routes.py's own documented
        // contract for the search route.
        const response = (await searchObjects(selectedType, queryText, {
          pageToken: pageToken ?? undefined,
          orderBy: orderBy || undefined,
          // Both sources AND together, matching how conditions
          // combine everywhere else: narrowing by a chart click and by
          // a typed filter narrows twice.
          conditions: [...asConditions(crossFilter), ...barFilters],
        })) as {
          results: SearchResult[]
          total_matches: number
          next_page_token?: string | null
        }
        if (isStale(thisRequestId)) return
        setResults(response.results)
        setTotalMatches(response.total_matches)
        setNextPageToken(response.next_page_token ?? null)
      } catch (err) {
        if (isStale(thisRequestId)) return
        if (handleIfSessionExpired(err, onSessionExpired)) return
        setError(getErrorMessage(err))
      } finally {
        if (!isStale(thisRequestId)) setLoading(false)
      }
    }, DEBOUNCE_MS)

    return () => clearTimeout(timeoutId)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, queryText, pageToken, orderBy, JSON.stringify(crossFilter), JSON.stringify(barFilters)])

  // Changing WHAT is searched resets WHERE you are in it. A token from
  // the old result set means nothing against the new one -- the server
  // would reject it or, worse, page into unrelated rows.
  useEffect(() => {
    setPageToken(null)
    setPreviousTokens([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedType, queryText, orderBy, JSON.stringify(crossFilter), JSON.stringify(barFilters)])

  if (objectTypes === null) {
    return (
      <div className="object-search">
        <LoadingState />
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

  // selectedType itself still starts as null -- the effect above sets
  // it to a real value once objectTypes is known, and the search
  // effect above correctly waits for that real value before firing
  // (gated on `if (!selectedType) return`). By the time results has
  // any entries at all, a real search must already have fired, which
  // itself guarantees selectedType was already a real string at that
  // point -- genuinely safe by construction, not assumed, the exact
  // same reasoning the <select> element's own fallback below already
  // relied on before this file had any types to make explicit.
  const currentType = selectedType ?? objectTypes[0]!

  // A TYPE ON THE MIDDLE RUNG. The caller holds discover: and not
  // read:, so they may know it exists and it yields no ids at all.
  //
  // Searching it would return an empty result set, which reads as "no
  // matches" -- a claim about the DATA when the truth is about their
  // access. Saying so is the difference between "there are none" and
  // "you may not see them".
  const searchable = visibleSchema?.[currentType]?.readable !== false
  // The current type's field metadata, for rendering hints the
  // ontology declares -- decimal places today.
  const typeSchemaFields = visibleSchema?.[currentType]?.fields

  return (
    // Workspace supplies the two-pane shape; this passes what goes in
    // each. The structure used to be three CSS class names nested by
    // hand, which meant getting it right was remembered rather than
    // enforced.
    <Workspace
      config={
        <>
          {/* The view selector first, because it decides what the
              controls below it apply to -- and in the same place
              Schema and Admin put theirs, so the shell reads one way
              throughout. */}
          <ViewSelector views={BROWSE_VIEWS} selected={view} onSelect={setView} />

          <SavedViews username={username} />

          <WorkspaceFilter label="Object type" htmlFor="object-type">
            <select
              id="object-type"
              aria-label="Object type"
              value={currentType}
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
          </WorkspaceFilter>

          {/* currentType, not selectedType: selectedType is null until
            someone picks one, while the panel already SHOWS the first
            type -- guarding on it would hide the filter bar on the
            very screen a user lands on. */}
          {visibleSchema?.[currentType] && (
            <WorkspaceFilter label="Filters">
              <FilterBar
                fields={visibleSchema[currentType]?.fields ?? {}}
                filters={barFilters}
                onChange={(next) => {
                  setBarFilters(next)
                  // A filter change is a new result set, so a page token
                  // from the old one means nothing.
                  setPageToken(null)
                }}
              />
            </WorkspaceFilter>
          )}
          <WorkspaceFilter label="Search" htmlFor="object-search-text">
            <input
              id="object-search-text"
              type="text"
              value={queryText}
              onChange={(event) => setQueryText(event.target.value)}
              placeholder={`Search ${currentType}…`}
            />
          </WorkspaceFilter>

          {sortableFields.length > 0 && (
            <WorkspaceFilter label="Sort by" htmlFor="object-search-sort">
              <HTMLSelect
                id="object-search-sort"
                aria-label="Sort by"
                value={orderBy}
                onChange={(event) => setOrderBy(event.currentTarget.value)}
              >
                <option value="">Default</option>
                {sortableFields.map((field) => (
                  <Fragment key={field.name}>
                    <option value={field.name}>{field.label} (A-Z)</option>
                    <option value={`${field.name}:desc`}>{field.label} (Z-A)</option>
                  </Fragment>
                ))}
              </HTMLSelect>
            </WorkspaceFilter>
          )}

          {/* Columns live with the other controls now, not in a
            disclosure above the results -- a configuration column is
            where configuration belongs, and it no longer has to hide
            to avoid pushing the results down the page. */}
          {selectedType && results.length > 0 && (
            <WorkspaceFilter label="Columns">
              {Object.keys(results[0]?.fields ?? {}).map((field) => {
                const shown = visibleColumns(Object.keys(results[0]?.fields ?? {})).includes(field)
                return (
                  <Checkbox
                    key={field}
                    checked={shown}
                    label={formatFieldName(field)}
                    onChange={() => {
                      const all = Object.keys(results[0]?.fields ?? {})
                      const current = chosenColumns[selectedType] ?? visibleColumns(all)
                      const next = shown ? current.filter((name) => name !== field) : [...current, field]
                      setChosenColumns({ ...chosenColumns, [selectedType]: next })
                    }}
                  />
                )
              })}
            </WorkspaceFilter>
          )}
        </>
      }
    >
      {error && <ErrorState>{error}</ErrorState>}
      {/* Two views of ONE object set. The filter is shared, so
          switching does not change what is being described -- only
          how. Stacking them, which this first did, made the page a
          scroll rather than a choice and gave the charts nowhere to
          breathe. */}
      {/* The canvas holds ONE view; the selector lives in the pane
          with Schema's and Admin's. A tab strip above the content
          meant this sub-app read left, then up, then down, where the
          other two read left to right. */}
      {view === 'charts' && selectedType && (
        <ChartsPanel
          objectType={selectedType}
          visibleSchema={visibleSchema}
          queryText={queryText}
          filters={crossFilter}
          onSelect={toggleChartValue}
          onSessionExpired={onSessionExpired}
        />
      )}

      {/* WHAT IS NARROWING THIS VIEW, said out loud. A cross-filter
          used to render nowhere in table view, so arriving from a link
          the panel said "Showing 2 of 2 matches" with no sign a filter
          was in force -- which reads as "there are 2 in the system".
          Foundry treats this as a first-class concern: Object Views
          ships a dedicated Active Filters widget for exactly it. */}
      <ActiveFilters filters={crossFilter} onRemove={removeCrossFilter} />

      {/* WHAT AN ACTION WOULD APPLY TO. Above the results, like the
          filter pills, because it describes what is about to be read
          -- and because "no selection" means ALL matches rather than
          none, which is not guessable. */}
      <div className="selection-row">
        <SelectionBar
          selectedCount={selectedIds.size}
          matchCount={totalMatches}
          pageCount={results.length}
          selectingAll={selectingAll}
          onSelectAllMatching={
            totalMatches > results.length
              ? () => {
                  // RESOLVED BY THE SERVER, at the moment of selection.
                  // What travels onward is the id list, never the
                  // filter -- a reviewer approves specific changes, and
                  // a filter that outlived the selection would let an
                  // approval of 500 quietly become 520 overnight.
                  setSelectingAll(true)
                  void matchingIds(currentType, queryText, crossFilter)
                    .then((ids) => setSelectedIds(new Set(ids)))
                    .catch((err: unknown) => setError(getErrorMessage(err)))
                    .finally(() => setSelectingAll(false))
                }
              : undefined
          }
          onClear={() => setSelectedIds(new Set())}
        />
        {/* ONLY ACTIONS THE ONTOLOGY MADE BULK-CAPABLE. The menu
            filters on an object_reference_list parameter of THIS
            object type; anything else would be accepted by the form
            and refused at the far end, after a whole form was
            filled. */}
        {selectedType !== null && results.length > 0 && (
          <BulkActionsMenu
            actions={actionTypes}
            objectType={currentType}
            count={selectedIds.size > 0 ? selectedIds.size : totalMatches}
            onChoose={setBulkAction}
          />
        )}
      </div>

      {bulkAction !== null && (
        <BulkActionForm
          action={bulkAction}
          objectType={currentType}
          // NO SELECTION MEANS THE WHOLE FILTERED SET -- Foundry's rule
          // -- and it is resolved HERE rather than in the form, so the
          // rule lives in one place. The form is told the ids and does
          // not know how they were chosen.
          // THE PAGE, NOT EVERY MATCH, and the selection bar says so.
          //
          // Foundry's rule is that an action applies to "all objects,
          // if none are selected", and their select-all "selects all
          // objects matching the applied filters, not just the objects
          // on the current page". We cannot honour that half: the
          // panel holds one PAGE of results, and total_matches counts
          // every match.
          //
          // So the promise is narrowed rather than the behaviour
          // faked. Sending results.map() while the bar claimed N
          // matches would touch fewer objects than a person was just
          // told -- a quiet under-application, which is worse than a
          // refusal because nothing looks wrong afterwards.
          objectIds={selectedIds.size > 0 ? [...selectedIds] : results.map((result) => result.id)}
          onDone={() => {
            setBulkAction(null)
            setSelectedIds(new Set())
          }}
        />
      )}

      {loading && <p className="object-search__status">Searching…</p>}

      {/*
       * WHEN the data was current, stated rather than warned about.
       *
       * read_from_mirror is deployment-wide: when it is on, EVERY read
       * comes from the mirror, always. So a warning Callout here would
       * be permanently present, and a permanent warning is one people
       * stop seeing -- which is worse than none, because it looks like
       * the system is telling them something.
       *
       * A muted fact instead. "synced 4 minutes ago" and "synced 3
       * days ago" are both unremarkable to render and completely
       * different to read, and the analyst is the one who knows which
       * matters for the question they are asking.
       *
       * PendingWriteCard keeps its warning Callout, correctly: that is
       * a decision point, not continuous reading, and someone about to
       * approve a write against stale values should be interrupted.
       */}
      {freshness?.source === 'mirror' && (
        <p className="object-search__freshness">
          {freshness.last_synced_at
            ? `Showing mirrored data, synced ${formatTimestamp(freshness.last_synced_at)}.`
            : 'Showing mirrored data, which has not been synced yet.'}
        </p>
      )}

      {view === 'table' &&
        !loading &&
        results.length === 0 &&
        !error &&
        /*
         * TWO EMPTY STATES, not one. "Your filters matched nothing" and
         * "this type has no rows" are different facts and lead to
         * different next actions: clear the filters, or go and look
         * somewhere else. Collapsing them into one grey "No results."
         * -- which is what this was -- makes an analyst guess which.
         *
         * A THIRD STATE IS DELIBERATELY ABSENT, and it is not the one
         * added below. The spec this came from wants "results exist
         * but are not visible to you". Elysium's uniform denial means
         * the response never distinguishes "no rows" from "not
         * allowed", and that is a security property: saying hidden
         * rows exist leaks the existence of data the caller cannot
         * see. That state is still refused. See UI_ROADMAP.md.
         *
         * THE UNSEARCHABLE STATE IS A DIFFERENT FACT. It says nothing
         * about whether rows exist -- it reports the caller's own
         * GRANT, known before any query runs, and leaks nothing about
         * the data. "You may not search this" and "there is nothing
         * here" are answers to different questions, and rendering the
         * first as the second is what this avoids.
         */
        (!searchable ? (
          <NonIdealState
            icon="lock"
            title="You cannot search this type"
            description={
              `Your permissions let you know ${currentType} exists, and not what it ` +
              `holds. Nothing is hidden from the results below -- there are no ` +
              `results to hide.`
            }
          />
        ) : (
          <NonIdealState
            icon={hasFilters ? 'filter-remove' : 'search'}
            title={hasFilters ? 'No matches' : 'Nothing here yet'}
            description={
              hasFilters
                ? `No ${currentType} matches the filters you have applied.`
                : `No ${currentType} records are available to show.`
            }
            action={
              hasFilters ? (
                <Button icon="filter-remove" onClick={clearAllFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ))}

      {view === 'table' && (
        <CardList className="object-search__results">
          {results.map((result) => {
            const titleValue = getDisplayTitle(visibleSchema?.[currentType], result.fields, result.id)
            return (
              // interactive -- real hover feedback, matching every other
              // clickable Card this migration has already used it for.
              // The real "stretched link" pattern below (see index.css's
              // own comment on .object-search__link::after) is what
              // makes the WHOLE card clickable/keyboard-focusable, not
              // just interactive's own hover styling on its own.
              <Card key={result.id} interactive className="object-search__result">
                {/* OUTSIDE THE LINK, and above it. The stretched link
                    covers the whole card so clicking anywhere
                    navigates; a checkbox painted underneath would be
                    visible, unclickable, and would navigate instead of
                    selecting. .object-search__select gives it its own
                    stacking context. */}
                <Checkbox
                  className="object-search__select"
                  checked={selectedIds.has(result.id)}
                  onChange={() => toggleSelected(result.id)}
                  aria-label={`Select ${String(titleValue)}`}
                />
                <Link to={`/objects/${currentType}/${encodeURIComponent(result.id)}`} className="object-search__link">
                  <p className="object-search__result-title">{titleValue as React.ReactNode}</p>
                </Link>
                {titleValue !== result.id && <p className="object-search__result-subtitle">{result.id}</p>}
                <dl className="object-search__result-fields">
                  {visibleColumns(Object.keys(result.fields))
                    .map((field) => [field, result.fields[field]] as const)
                    .map(([field, value]) => (
                      <div key={field} className="object-search__result-field">
                        <dt>{formatFieldName(field)}</dt>
                        <dd>{formatValue(value, typeSchemaFields?.[field]?.decimal_places)}</dd>
                      </div>
                    ))}
                </dl>
              </Card>
            )
          })}
        </CardList>
      )}

      {view === 'table' && (nextPageToken || previousTokens.length > 0) && (
        <div className="object-search__pager">
          <Button
            minimal
            icon="chevron-left"
            disabled={previousTokens.length === 0}
            onClick={() => {
              // Pops the stack rather than computing a token. They are
              // opaque, so the only reliable previous page is the one
              // we actually came from.
              const stack = [...previousTokens]
              setPageToken(stack.pop() ?? null)
              setPreviousTokens(stack)
            }}
          >
            Previous
          </Button>
          <span className="object-search__more">
            {/* Deliberately NOT "page 3 of 12". A page number would
                promise a stability that a LIVE deployment does not
                provide -- default paging there may duplicate or miss
                rows as data changes underneath.

                AND THE TOTAL CARRIES THE SAME CAVEAT, which this line
                used to state unconditionally. On a live deployment
                "of 4,312" is a number that was true when the query
                ran and may not be true now; presenting it flatly
                invites someone to reconcile it against a report and
                find a discrepancy that is not one.

                ON A MIRROR IT IS EXACT, and saying so matters as much.
                A generation pins each table's snapshot, so every page
                of one query reads the same immutable data -- the count
                is authoritative and a UI that hedged it would
                understate what the deployment guarantees. */}
            Showing {results.length} of {totalMatches}
            {freshness?.source === 'live' ? ' matches at the time of this query' : ' matches'}
          </span>
          <Button
            minimal
            rightIcon="chevron-right"
            disabled={!nextPageToken}
            onClick={() => {
              setPreviousTokens([...previousTokens, pageToken ?? ''])
              setPageToken(nextPageToken)
            }}
          >
            Next
          </Button>
        </div>
      )}
    </Workspace>
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
// - The TypeScript migration reused the SAME selectedType ?? objectTypes
//   [0] fallback (renamed currentType, used everywhere selectedType
//   was needed after the two early returns, not just the <select>'s
//   own value) rather than inventing a second pattern for the exact
//   same "safe by construction, TypeScript can't itself prove it"
//   situation results.map() and the search Link also depend on.
// - Blueprint migration: CardList/Card for the results list, replacing
//   a bare <ul>/<li>; Callout intent="danger" for the error message,
//   same as every other error Callout this migration -- part of the
//   ObjectSearchPanel/ObjectDetailPanel step discussed directly with
//   the person (Card/CardList, Callout, Button).
//
//   A real, structural constraint drove the exact shape here, not a
//   free styling choice: Card must be CardList's own DIRECT child --
//   confirmed directly against Blueprint's real, shipped CSS, its own
//   borders/hover states/rounded corners all key off a real
//   `.bp6-card-list > .bp6-card` selector, which a <Link> wrapper in
//   between (this file's own original structure -- the whole card
//   WAS the link) would silently break. Card itself has no href prop
//   at all (confirmed against its real type definition), and Card
//   with a bare onClick is NOT keyboard-accessible on its own
//   (confirmed directly -- no tabindex, no role, no key handling in
//   its real, rendered DOM output) -- using that instead would have
//   been a real accessibility regression from the original, already-
//   accessible <Link>. Resolved with the real "stretched link"
//   pattern (the same one Bootstrap's own stretched-link utility
//   uses): only the title text is real, visible <Link> content, kept
//   in normal flow; a ::after pseudo-element (see index.css's own
//   comment) expands the actual clickable/keyboard-focusable hitbox
//   to cover the whole card. Confirmed live, forcing a click through
//   the overlay specifically (Playwright's own strict click-
//   interception check initially refused a plain click here, which
//   is itself real, positive confirmation the overlay genuinely
//   covers the click target, not a failure) -- clicking a FIELD, not
//   just the title, correctly navigated to the right, distinct
//   object.
//
//   A real, second Blueprint-CSS-override lesson found and fixed here
//   too, beyond Shell.tsx's own sidebar one -- confirmed directly, not
//   guessed at from the CSS source alone: a Card that's CardList's own
//   direct child gets `display: flex; align-items: center` from
//   Blueprint's own real, shipped CSS (its own deliberate "single-line
//   list row" default), which silently laid this card's own multi-line
//   content (title, subtitle, a whole fields table) out side-by-side
//   instead of stacked. Genuinely hard to find: an isolated
//   reproduction OUTSIDE a real CardList wrapper worked fine, which is
//   exactly what pointed at CardList's own direct-child rule
//   specifically as the real, missing piece, not the Card/Link markup
//   itself. Fixed with the same specificity-matching discipline
//   already established for the sidebar's own overrides -- two real,
//   genuinely-present classes together on each side of the child
//   combinator, reliably beating Blueprint's own rule regardless of
//   source order. A real, honest reminder of why this needed live,
//   visual verification at all: jsdom-based unit tests never apply
//   real CSS layout, so all 20 existing tests passed throughout this
//   entire investigation, oblivious to the real, visually-broken
//   layout the whole time.
// - The latestRequestId stale-response guard extracted to a real,
//   shared useLatestRequestGuard() hook (@elysium/shell-api), found
//   as a genuine, un-acted-on DRY gap during a later, full-migration
//   review pass: ObjectDetailPanel.tsx's own comment already,
//   explicitly said "Same stale-response guard as ObjectSearchPanel's
//   own live search" -- correctly IDENTIFIED as the same pattern, but
//   never actually extracted, leaving two real, independent copies
//   that could silently drift. Same real, live behavior confirmed
//   unchanged both ways: the existing race-condition test here still
//   passes unchanged, and a real, live browser walkthrough (live
//   search, then rapid navigation between two different objects)
//   confirmed no stale content ever showed. The hook itself also
//   gained its own, new, isolated unit tests -- a genuine, additional
//   benefit of extracting it at all, not just observable indirectly
//   through this file's and ObjectDetailPanel.tsx's own much larger
//   integration tests.
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
