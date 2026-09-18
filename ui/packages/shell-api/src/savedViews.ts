/**
 * savedViews.ts -- "let me find that again".
 *
 * A SAVED VIEW IS A URL AND A NAME. Nothing more, because Browse's
 * view state already lives in the query string: the object type, the
 * search, the sort, the chart filters and the tab. Persisting one is
 * storing a string, not designing a schema for view state -- and a
 * schema would have to be revised every time a panel gained a knob.
 *
 * PERSONAL, NOT SHARED, and the URL work is why. Sharing a view is
 * already solved: send the link. What a saved view answers is the
 * other question -- "the thing I set up on Tuesday, where did it go"
 * -- and that is about one person's memory rather than a team's
 * agreement.
 *
 * So no permission model, no server store, no ownership rules. If
 * shared explorations are wanted later they are a different feature
 * with a different shape, not a flag on this one.
 *
 * STORAGE IS A HINT; THE SERVER IS THE AUTHORITY. browserPreferences'
 * own docstring makes the point about columns and it holds here more
 * strongly: a saved view naming an object type the user has since lost
 * access to opens and shows nothing, because the schema is re-fetched
 * and re-authorised on every load. A stale saved view is a dead link,
 * never a way back into data.
 *
 * DEGRADES RATHER THAN BREAKS, inherited from the same module: browser
 * storage throws in private mode, on quota, with cookies disabled. A
 * failure to save loses a convenience, and must not lose the view the
 * person is currently looking at.
 */

import { readPreference, writePreference } from './browserPreferences'

export interface SavedView {
  /** What the person called it. Their words, not a generated summary
   *  -- "Q3 refunds to chase" means something no derived title would. */
  name: string
  /** Path plus query string, exactly as the address bar had it. */
  url: string
  /** ISO 8601. Used for ordering, and for telling someone a view is
   *  old enough to be worth re-checking. */
  saved_at: string
}

const KEY = 'savedViews'

/** Everything this user has saved, newest first. */
export function listSavedViews(username: string): SavedView[] {
  const stored = readPreference<SavedView[]>(KEY, username, [])
  if (!Array.isArray(stored)) return []
  // FILTERED, NOT TRUSTED. localStorage is editable by hand and
  // survives across versions of this code, so an entry from an older
  // shape must be skipped rather than rendered as `undefined`.
  return stored
    .filter((view) => view && typeof view.name === 'string' && typeof view.url === 'string')
    .sort((a, b) => (b.saved_at ?? '').localeCompare(a.saved_at ?? ''))
}

/** Saves a view, replacing any with the same name.
 *
 * REPLACING RATHER THAN DUPLICATING, because saving twice under one
 * name is how a person UPDATES a view -- they changed a filter and
 * want the name to mean the new thing. Two entries with one name would
 * make the list unusable and leave no way to correct it.
 */
export function saveView(username: string, name: string, url: string): SavedView[] {
  const trimmed = name.trim()
  if (trimmed === '') return listSavedViews(username)

  const next = [
    { name: trimmed, url, saved_at: new Date().toISOString() },
    ...listSavedViews(username).filter((view) => view.name !== trimmed),
  ]
  writePreference(KEY, username, next)
  return next
}

/** Forgets one, by name. */
export function deleteView(username: string, name: string): SavedView[] {
  const next = listSavedViews(username).filter((view) => view.name !== name)
  writePreference(KEY, username, next)
  return next
}
