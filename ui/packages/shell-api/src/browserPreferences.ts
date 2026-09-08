/**
 * browserPreferences.ts -- small per-user choices that survive a
 * navigation.
 *
 * A panel's React state dies when its route unmounts. That is right
 * for what a screen is currently DOING and wrong for what a user has
 * CHOSEN: picking result columns, then opening one result and coming
 * back, should not silently undo the choice. Found exactly that way.
 *
 * KEYED BY USERNAME, because localStorage is per-BROWSER. Without it a
 * second person on the same machine inherits the first's preferences.
 * The same rule app-schema's Discover storage follows, extracted here
 * so the next screen that needs it does not write a third copy.
 *
 * NOT FOR ANYTHING THE SERVER DECIDES. These are cosmetic choices --
 * which columns, which sort. What a caller may READ is re-derived from
 * the visible schema on every load, so a stored preference naming a
 * field they have since lost access to simply has no effect. Storage
 * is a hint; the schema is the authority.
 *
 * DEGRADES RATHER THAN BREAKS. Browser storage is editable by hand and
 * can throw outright -- private mode, quota, disabled cookies. A
 * malformed value is treated as absent and a throw is swallowed:
 * losing a column choice is acceptable, breaking the page it decorates
 * is not.
 */

function key(name: string, username: string): string {
  return `elysium.pref.${name}.${username}`
}

export function readPreference<T>(name: string, username: string, fallback: T): T {
  try {
    const raw = window.localStorage.getItem(key(name, username))
    return raw === null ? fallback : (JSON.parse(raw) as T)
  } catch {
    return fallback
  }
}

export function writePreference(name: string, username: string, value: unknown): void {
  try {
    window.localStorage.setItem(key(name, username), JSON.stringify(value))
  } catch {
    // See this module's header: a lost preference is acceptable, a
    // thrown render is not.
  }
}
