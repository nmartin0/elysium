/**
 * SavedViews -- a search worth coming back to.
 *
 * ON THE SERVER, NOT IN THE BROWSER. These were `{name, url}` in
 * localStorage, which worked perfectly for a person returning to a
 * search and was invisible to everything else. A trigger that watches
 * a view runs after a sync, and cannot read a browser.
 *
 * A STORED QUERY RATHER THAN A URL. `type`, `q` and `filters`
 * describe WHAT MATCHES and go to the server as a query a condition
 * can evaluate. `sort` and `view` describe how this person likes to
 * look at it, and travel separately as `presentation` -- kept, so
 * restoring a view does not lose somebody's sort order, but out of
 * the way of anything counting rows.
 *
 * THE POPOVER STILL WORKS THE SAME WAY, which is the point: moving
 * where something lives should not move where somebody clicks.
 */

import { Button, InputGroup, Menu, MenuDivider, MenuItem, Popover } from '@blueprintjs/core'
import {
  deleteSavedView,
  getSavedViews,
  handleIfSessionExpired,
  saveSavedView,
  type ServerSavedView,
} from '@elysium/shell-api/api'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'

import WatchDialog from './WatchDialog'

interface SavedViewsProps {
  /** Only to tell one person's popover from another's in a test; the
   *  server decides whose views these are. */
  username: string
  onSessionExpired?: () => void
}

/** The keys that describe how a view is LOOKED AT, as opposed to what
 *  it matches. Kept, but separately. */
const PRESENTATION_KEYS = ['sort', 'view'] as const

function urlFor(view: ServerSavedView): string {
  const params = new URLSearchParams()
  if (view.object_type) params.set('type', view.object_type)
  if (view.query_text) params.set('q', view.query_text)
  if (view.conditions.length > 0) params.set('filters', JSON.stringify(view.conditions))
  for (const key of PRESENTATION_KEYS) {
    const value = view.presentation[key]
    if (typeof value === 'string' && value !== '') params.set(key, value)
  }
  return `/browse?${params.toString()}`
}

export default function SavedViews({ username, onSessionExpired }: SavedViewsProps) {
  const location = useLocation()
  const navigate = useNavigate()
  const [views, setViews] = useState<ServerSavedView[]>([])
  const [name, setName] = useState('')
  const [open, setOpen] = useState(false)
  // THE VIEW BEING SET UP TO WATCH, or null. A dialog rather than
  // another menu level: a threshold needs a number and a choice, and
  // a submenu that asks for both is a form pretending not to be one.
  const [watching, setWatching] = useState<ServerSavedView | null>(null)

  const params = new URLSearchParams(location.search)
  const objectType = params.get('type') ?? ''

  /**
   * The session callback through a ref, so `load` has NO dependencies
   * and the effect below runs once.
   *
   * MEASURED BEFORE THE FIX: three renders of the parent, three
   * fetches. App.tsx declares handleSessionExpired as a plain function
   * inside the component, so it is a new identity on every render;
   * `load` was built with useCallback([onSessionExpired]) and run from
   * useEffect([load]), so each parent render rebuilt `load` and
   * refired the effect. Exactly the bug useFetchOnce's own notes
   * record -- the schema fetched three times per page load -- in a
   * panel that does not use useFetchOnce because it needs to REFETCH
   * after an action.
   */
  const latestSessionExpired = useRef(onSessionExpired)
  useEffect(() => {
    latestSessionExpired.current = onSessionExpired
  })

  const load = useCallback(async () => {
    try {
      setViews(await getSavedViews())
    } catch (caught: unknown) {
      const expired = latestSessionExpired.current
      if (expired && handleIfSessionExpired(caught, expired)) return
      // A POPOVER THAT CANNOT LIST is still one that can save.
      // Failing quietly here beats an error banner over a search that
      // is working.
      setViews([])
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  // THE VIEW ALREADY SAVED AT THIS SEARCH, so re-opening the popover
  // on one you saved offers to update it rather than duplicate it.
  const currentUrl = `${location.pathname}${location.search}`
  const existing = views.find((view) => urlFor(view) === currentUrl)

  async function save() {
    const trimmed = name.trim()
    if (trimmed === '' || objectType === '') return

    let conditions: Array<Record<string, unknown>> = []
    try {
      const raw = params.get('filters')
      if (raw !== null) conditions = JSON.parse(raw)
    } catch {
      // A FILTER THAT WILL NOT PARSE saves as no filter rather than
      // refusing the save -- the URL is editable by hand, and the
      // same tolerance useUrlJson already applies.
      conditions = []
    }

    const presentation: Record<string, string> = {}
    for (const key of PRESENTATION_KEYS) {
      const value = params.get(key)
      if (value !== null && value !== '') presentation[key] = value
    }

    try {
      await saveSavedView({
        name: trimmed,
        object_type: objectType,
        query_text: params.get('q') ?? '',
        conditions,
        presentation,
      })
      await load()
      setOpen(false)
      setName('')
    } catch (caught: unknown) {
      if (latestSessionExpired.current) handleIfSessionExpired(caught, latestSessionExpired.current)
    }
  }

  async function forget(viewId: string) {
    try {
      await deleteSavedView(viewId)
      await load()
    } catch (caught: unknown) {
      if (latestSessionExpired.current) handleIfSessionExpired(caught, latestSessionExpired.current)
    }
  }

  return (
    <>
      <WatchDialog view={watching} onClose={() => setWatching(null)} onSessionExpired={onSessionExpired} />
      <Popover
        isOpen={open}
        onInteraction={(next) => {
          setOpen(next)
          if (next) setName(existing?.name ?? '')
        }}
        content={
          <Menu className="saved-views__menu">
            <div className="saved-views__save">
              <InputGroup
                placeholder="Name this view…"
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') void save()
                }}
              />
              <Button
                small
                intent="primary"
                disabled={name.trim() === '' || objectType === ''}
                onClick={() => void save()}
              >
                {existing && existing.name === name.trim() ? 'Update' : 'Save'}
              </Button>
            </div>
            {views.length > 0 && <MenuDivider title="Saved" />}
            {views.map((view) => (
              <MenuItem
                key={view.view_id}
                text={view.name}
                data-username={username}
                onClick={() => {
                  setOpen(false)
                  navigate(urlFor(view))
                }}
                labelElement={
                  <>
                    <Button
                      minimal
                      small
                      icon="eye-open"
                      aria-label={`Watch ${view.name}`}
                      onClick={(event) => {
                        event.stopPropagation()
                        setOpen(false)
                        setWatching(view)
                      }}
                    />
                    <Button
                      minimal
                      small
                      icon="cross"
                      aria-label={`Forget ${view.name}`}
                      onClick={(event) => {
                        // Not the MenuItem's own click, or forgetting a
                        // view would navigate to it first.
                        event.stopPropagation()
                        void forget(view.view_id)
                      }}
                    />
                  </>
                }
              />
            ))}
          </Menu>
        }
      >
        <Button icon="bookmark" small>
          {existing ? existing.name : 'Saved views'}
        </Button>
      </Popover>
    </>
  )
}
