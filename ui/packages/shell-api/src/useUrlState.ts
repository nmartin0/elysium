/**
 * useUrlState -- state that lives in the query string.
 *
 * WHAT BELONGS HERE, and what does not, is the whole decision.
 *
 * A VIEW is what you are currently looking at: the object type, the
 * search text, the sort, the chart filters, which tab. Someone wants
 * to send it to a colleague, bookmark it, or find it again in their
 * browser history. It is a property of the QUESTION, not the person.
 *
 * A PREFERENCE is how you like things shown -- which columns, the
 * theme, a collapsed sidebar. It follows you across every view and
 * belongs in readPreference/writePreference, which is where Browse's
 * column choices already are. Putting a preference in the URL would
 * mean sharing a link that changes the recipient's settings.
 *
 * NOT IN THE URL EITHER: page tokens. They are opaque, server-issued
 * and short-lived, so a shared link carrying one would either 404 or
 * silently return a different page than the sender saw. A shared view
 * starts at the first page, which is the honest answer -- the RESULTS
 * are not what is being shared, the question is.
 *
 * REPLACE, NOT PUSH. Typing in a search box would otherwise write one
 * history entry per keystroke, and Back would walk backwards through
 * the letters of a word. The browser Back button should leave the
 * view, not un-type it.
 */

import { useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'

/** Clears several keys in ONE navigation.
 *
 * WHY THIS EXISTS AND A LOOP DOES NOT WORK. Each useUrlValue call has
 * its own useSearchParams, and setSearchParams NAVIGATES rather than
 * queueing like setState. Two setters called in one handler therefore
 * issue two navigations from the same starting params, and the second
 * discards the first.
 *
 * Found by a test, not by review: Browse's "clear filters" button
 * resets the search text AND the chart filters, and after the move to
 * URL state only one of them cleared. The button looked like it half
 * worked.
 */
export function useClearUrlKeys(): (keys: string[]) => void {
  const [, setParams] = useSearchParams()

  return useCallback(
    (keys: string[]) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          for (const key of keys) updated.delete(key)
          return updated
        },
        { replace: true },
      )
    },
    [setParams],
  )
}

/** Reads one value, with a fallback for when it is absent. */
export function useUrlValue(key: string, fallback: string): [string, (next: string) => void] {
  const [params, setParams] = useSearchParams()

  const set = useCallback(
    (next: string) => {
      setParams(
        (current) => {
          const updated = new URLSearchParams(current)
          // ABSENT RATHER THAN EMPTY. `?q=` in a shared link is noise
          // that means the same as no q at all, and a URL a person
          // might paste into a message should carry only what it needs.
          if (next === fallback || next === '') {
            updated.delete(key)
          } else {
            updated.set(key, next)
          }
          return updated
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )

  return [params.get(key) ?? fallback, set]
}

/** Reads a JSON-encoded value, for state that is not a plain string.
 *
 * A MALFORMED VALUE FALLS BACK rather than throwing. Query strings are
 * edited by hand, truncated by chat clients and mangled by link
 * previewers -- a view that refuses to load because someone's mail
 * client ate a bracket is worse than one that opens unfiltered.
 */
export function useUrlJson<T>(key: string, fallback: T): [T, (next: T | ((current: T) => T)) => void] {
  const [params, setParams] = useSearchParams()

  const raw = params.get(key)
  let value = fallback
  if (raw !== null) {
    try {
      value = JSON.parse(raw) as T
    } catch {
      value = fallback
    }
  }

  const set = useCallback(
    // THE UPDATER FORM, as useState supports. A caller toggling one
    // entry of a list must be able to read the CURRENT value rather
    // than a captured one -- Browse's chart cross-filter does exactly
    // that, and closing over a stale array would drop a click made
    // before the previous render committed.
    (next: T | ((current: T) => T)) => {
      setParams(
        (currentParams) => {
          const updated = new URLSearchParams(currentParams)
          const raw = currentParams.get(key)
          let current = fallback
          if (raw !== null) {
            try {
              current = JSON.parse(raw) as T
            } catch {
              current = fallback
            }
          }
          const resolved = typeof next === 'function' ? (next as (value: T) => T)(current) : next
          const encoded = JSON.stringify(resolved)
          if (encoded === JSON.stringify(fallback)) {
            updated.delete(key)
          } else {
            updated.set(key, encoded)
          }
          return updated
        },
        { replace: true },
      )
    },
    [key, fallback, setParams],
  )

  return [value, set]
}
