/**
 * discoverStorage.ts -- recently viewed and favourited object types.
 *
 * Browser-local, per username. Deliberately NOT a backend store: a
 * recently-viewed list is per-device by nature, and a server round
 * trip to remember which tab someone had open is the wrong shape.
 * Favourites arguably want to follow a user between machines; that is
 * a known, deferred addition with a real trigger, not an oversight.
 *
 * TWO RULES MAKE THIS SAFE, and both matter:
 *
 * 1. KEYED BY USERNAME. localStorage is per-BROWSER, so without this a
 *    second user on the same machine would inherit the first's lists.
 *
 * 2. THE SCHEMA IS THE AUTHORITY, ALWAYS. Every read is filtered
 *    through the caller's CURRENT visible schema before it is
 *    returned. Stored names are a hint about ordering; they never
 *    decide what a user may see.
 *
 * Rule 2 is what makes permission changes safe in both directions. A
 * user who loses access to a type still has its name in their storage,
 * and it silently stops appearing. A user who GAINS access sees the
 * type immediately, because the schema is re-read on every load rather
 * than reconciled against a cached copy. Nothing needs migrating when
 * a role changes, because nothing was ever trusted.
 *
 * The stored names are object type API names -- not data, not values,
 * and not evidence a user could read them. A name in storage that the
 * schema does not confirm is treated as absent.
 */

const RECENT_LIMIT = 8

function key(kind: 'recent' | 'favourites', username: string): string {
  return `elysium.${kind}.${username}`
}

function read(kind: 'recent' | 'favourites', username: string): string[] {
  try {
    const raw = window.localStorage.getItem(key(kind, username))
    const parsed: unknown = raw === null ? [] : JSON.parse(raw)
    // Anything but an array of strings is treated as absent rather
    // than trusted: this is browser storage, editable by hand, and a
    // malformed value must not break the page it decorates.
    return Array.isArray(parsed) ? parsed.filter((item): item is string => typeof item === 'string') : []
  } catch {
    // Storage can throw outright -- disabled cookies, private mode,
    // quota. A convenience feature must degrade to "no history", never
    // to a broken app.
    return []
  }
}

function write(kind: 'recent' | 'favourites', username: string, values: string[]): void {
  try {
    window.localStorage.setItem(key(kind, username), JSON.stringify(values))
  } catch {
    // Same reasoning: losing a favourite is acceptable, throwing is
    // not.
  }
}

/** Names the caller can actually see right now, in stored order. */
function visibleOnly(names: string[], visibleTypes: readonly string[]): string[] {
  const allowed = new Set(visibleTypes)
  return names.filter((name) => allowed.has(name))
}

export function getRecent(username: string, visibleTypes: readonly string[]): string[] {
  return visibleOnly(read('recent', username), visibleTypes)
}

export function recordVisit(username: string, objectType: string): void {
  const existing = read('recent', username).filter((name) => name !== objectType)
  write('recent', username, [objectType, ...existing].slice(0, RECENT_LIMIT))
}

export function getFavourites(username: string, visibleTypes: readonly string[]): string[] {
  return visibleOnly(read('favourites', username), visibleTypes)
}

export function isFavourite(username: string, objectType: string): boolean {
  return read('favourites', username).includes(objectType)
}

export function toggleFavourite(username: string, objectType: string): boolean {
  const existing = read('favourites', username)
  const next = existing.includes(objectType)
    ? existing.filter((name) => name !== objectType)
    : [...existing, objectType]
  write('favourites', username, next)
  return next.includes(objectType)
}
