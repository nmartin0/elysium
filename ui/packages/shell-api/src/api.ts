// api.ts  (the ONE place that knows about fetch, the session/CSRF
// cookies, and the /api prefix)
//
// Every caller in this file passes a plain, unprefixed path ("/login",
// not "/api/login") -- apiFetch() itself is the one place that adds
// the real /api prefix (see its own comment). This works correctly in
// BOTH modes without any configuration: Vite's dev-server proxy (see
// vite.config.js) forwards /api/* to the real backend during
// development, and the built app is served BY FastAPI itself in
// production (see api/app.py), so requests are already same-origin
// there too. No environment variable, no base URL to get wrong
// between dev and prod.
//
// The /api prefix itself is STILL load-bearing, for a related but now
// slightly different reason than before: a client-side react-router-
// dom route and a real backend path could still collide (e.g. both
// /objects/{type}/{id}) without it -- and now that the session lives
// in a real cookie (see below), a raw browser navigation to that
// bookmarked URL would no longer even hit a 401 (a cookie, unlike the
// old Authorization header, IS automatically sent on a plain page
// navigation) -- it would render the backend's own raw JSON response
// directly instead of ever loading this app. Still a real bug this
// prefix structurally prevents, just a different failure shape than
// the original one that motivated it. See api/app.py's own
// include_router() call for the fuller history.
//
// The session token is NO LONGER stored or managed by this file AT
// ALL -- it lives in a real, httponly cookie (core/auth/
// auth_cookies.py), set and cleared entirely by the backend's own
// Set-Cookie responses, invisible to and unreachable by this or any
// other JavaScript running on the page. This is the whole point:
// even a hypothetical future XSS bug in this app could never read it.
// The browser attaches it automatically on every same-origin request;
// this file's own job shrank considerably as a direct result -- see
// git history for the real localStorage-based mechanism this
// replaced, and the security review that motivated the change.
//
// The CSRF token, by contrast, DOES need to be read here -- it lives
// in a second, deliberately NOT httponly cookie (elysium_csrf) for
// exactly this reason: same-origin JS reads its value and echoes it
// back as a real request header (X-CSRF-Token) on every state-
// changing call. This works because a cross-site attacker page can
// never read a cookie set by this origin (same-origin policy), so it
// can never construct a matching header value -- even in the rare
// cases SameSite=Strict alone doesn't fully cover. See api/
// csrf_middleware.py's own docstring for the complete reasoning.
//
// RETURN TYPES: every function here that hands back response.json()
// is typed Promise<unknown>, deliberately, not a hand-authored
// interface per endpoint -- fetch's own .json() is typed `any` in
// TypeScript's built-in lib, and `any` is contagious (it silently
// disables checking everywhere it flows), which would quietly undo
// the whole point of converting this file at all. unknown is the
// honest alternative: cheap here (one word per function), and it
// forces each REAL consumer to narrow to the specific shape it
// already assumes from its own usage -- done at each component's own
// conversion step, not front-loaded here as a much larger, separate
// piece of work authoring a matching interface for every backend
// response shape up front.

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// The ONE place this project's own "a 401 means the session expired,
// go back to login" rule is expressed -- previously duplicated,
// byte-for-byte, in nine separate catch blocks across this app
// (PendingWriteCard, ObjectSearchPanel, ObjectDetailPanel twice,
// ActionForm, AdminPanel four times, App.jsx twice) before being
// extracted here. Returns true when it already called onSessionExpired
// -- every caller's own catch block follows the same shape:
//
//   if (handleIfSessionExpired(err, onSessionExpired)) return
//   setError(getErrorMessage(err))   // or whatever this call site does otherwise
//
// Deliberately narrow -- extracts ONLY the part that was genuinely
// identical everywhere. The surrounding try/catch/finally shape still
// varies per call site (different success-path state, different
// finally cleanup), and folding THAT into a generic "run this and
// handle errors" wrapper too would trade real, if repetitive, clarity
// at each call site for a more abstract, harder-to-follow one -- not
// attempted here for that reason, not an oversight.
//
// err: unknown, not Error -- a catch block's own binding is genuinely
// unknown in strict mode (useUnknownInCatchVariables, bundled into
// strict: true) since JavaScript allows throwing anything at all, not
// just Error instances; the `instanceof ApiError` check below is
// exactly how a caller safely narrows it.
export function handleIfSessionExpired(err: unknown, onSessionExpired: () => void): boolean {
  if (err instanceof ApiError && err.status === 401) {
    onSessionExpired()
    return true
  }
  return false
}

// A second, real, whole-codebase DRY extraction, alongside
// handleIfSessionExpired above -- `err instanceof Error ? err.message
// : String(err)` was found duplicated, byte-for-byte, NINE times
// across six different files (AdminPanel four times,
// ObjectDetailPanel, ActionForm, ObjectSearchPanel, LoginForm,
// PendingWriteCard), every single one of them the same, standard
// "safely narrow an unknown catch variable to a real, displayable
// string" idiom -- ApiError's own real .message (set via its
// constructor) already carries api.ts's own safe, generic message for
// every real HTTP failure (see apiFetchOrThrow's own body.detail
// fallback), so this is never showing a raw, unexpected value to the
// person using the app; it's just the one, safe way to also handle
// the rarer case of something non-Error being thrown at all (which
// JavaScript genuinely permits).
export function getErrorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err)
}

const CSRF_COOKIE_NAME = 'elysium_csrf'
const CSRF_HEADER_NAME = 'X-CSRF-Token'
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS', undefined]) // undefined = fetch's own default, GET

// Reads a single, specific cookie's own value out of document.cookie
// -- there is no built-in browser API for this. Deliberately does
// NOT reach for a general-purpose cookie-parsing library for one,
// narrow, single-cookie read; a tiny, direct regex is simpler and has
// nothing to go wrong that a library would meaningfully protect
// against here. Returns null (not '' or undefined) when the cookie
// genuinely isn't set -- e.g. before any login has ever happened, or
// after logout() has cleared it -- so callers can tell "no CSRF
// cookie exists yet" apart from "it exists and is empty" (which never
// legitimately happens, but null is still the more honest absence
// value than an empty string would be).
function getCsrfCookie(): string | null {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`))
  // match[1]! -- noUncheckedIndexedAccess types every array index as
  // possibly-undefined, including a regex match's own capture groups;
  // genuinely safe here by construction, not assumed: this regex has
  // exactly one capture group, so a truthy `match` guarantees index 1
  // matched something real (possibly an empty string, from the `*`,
  // but never undefined).
  return match ? decodeURIComponent(match[1]!) : null
}

/**
 * Which configuration answered us last, and who to tell when it moves.
 *
 * THE PROBLEM. The UI fetches a user's visible schema ONCE, at login,
 * and never again. A configuration reload changes what the server will
 * answer, and the browser goes on believing what it was told.
 *
 * Found by using it: a field moved to `discover:` was correctly
 * withheld by the server, arriving as null, and rendered as "not set"
 * because the cached schema still said it was readable. The right
 * answer only appeared after a manual browser refresh.
 *
 * NO POLLING. Every response carries the serving generation, so the
 * client notices on its NEXT request -- whatever that request is --
 * rather than asking on a timer for news that usually has not come.
 */
let lastSeenGeneration: string | null = null
let onGenerationChange: (() => void) | null = null

/** Forgets which generation was last seen.
 *
 * FOR TESTS, and it earns its place rather than being a convenience:
 * the baseline is module state, so one test leaving it at "8" makes
 * the next test's "7" look like a reload. Without this, these tests
 * would pass or fail by ORDER, which is the kind of flake that gets
 * diagnosed as something else entirely.
 *
 * Harmless in production -- nothing calls it, and calling it would at
 * worst cost one extra refetch.
 */
export function forgetLastSeenGeneration(): void {
  lastSeenGeneration = null
}

/** Registers the callback fired when the server's configuration moves.
 *  The shell uses it to refetch the schema and the app list. */
export function setGenerationChangeHandler(handler: () => void): void {
  onGenerationChange = handler
}

function noticeGeneration(response: Response): void {
  // DEFENSIVE ABOUT THE RESPONSE SHAPE, because this runs on EVERY
  // call and a throw here would fail requests that were otherwise
  // fine. Test doubles return objects without headers, and a fetch
  // that rejected mid-flight can too -- neither is a reason to break
  // the call it was attached to.
  const current = response?.headers?.get?.('x-elysium-generation') ?? null
  // AN ABSENT HEADER IS NOT A CHANGE. A static file, or a response
  // from before this shipped, must not look like a reload -- that
  // would refetch the schema on every page load forever.
  if (current === null) return

  const previous = lastSeenGeneration
  lastSeenGeneration = current
  // The FIRST response establishes the baseline rather than firing.
  // Otherwise logging in would immediately refetch what it just
  // fetched.
  if (previous !== null && previous !== current) onGenerationChange?.()
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const headers = {
    'Content-Type': 'application/json',
    ...options.headers,
  }
  // Only for state-changing methods -- matches api/csrf_middleware.py's
  // own exemption for safe methods exactly, and naturally, correctly
  // does nothing extra for /login itself: no elysium_csrf cookie
  // exists yet at that point (nobody has a session yet), so
  // getCsrfCookie() returns null and no header gets added at all --
  // the backend's own middleware already, separately exempts /login
  // by path regardless, so this isn't relied upon for that specific
  // exemption, just a natural, harmless consequence of it.
  if (!SAFE_METHODS.has(options.method)) {
    const csrfToken = getCsrfCookie()
    if (csrfToken) (headers as Record<string, string>)[CSRF_HEADER_NAME] = csrfToken
  }
  // Every real backend path lives under /api -- see this file's own
  // header comment for the fuller reasoning. This is the ONE place
  // that needs to know this -- every caller in this file passes a
  // plain, unprefixed path like '/login'.
  //
  // credentials: 'same-origin' set EXPLICITLY, even though it's
  // already the real, current spec default (confirmed directly
  // against the Fetch Standard itself, not assumed from memory) --
  // zero-cost, and removes any ambiguity about whether the session
  // cookie actually gets attached, which this entire mechanism now
  // depends on.
  const response = await fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' })
  noticeGeneration(response)
  return response
}

// Throws ApiError on any non-2xx response -- used by calls where the
// caller only cares about success/failure, not the raw status (login,
// confirming a write). query() is deliberately DIFFERENT -- see below.
async function apiFetchOrThrow(path: string, options: RequestInit = {}): Promise<Response> {
  const response = await apiFetch(path, options)
  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new ApiError(response.status, body.detail || `Request failed (${response.status})`)
  }
  return response
}

// No return value -- the real session and CSRF cookies are set
// entirely by the backend's own Set-Cookie response headers; there is
// nothing left for this function to store or hand back. Still throws
// ApiError on a real failure (wrong credentials, locked out), same as
// before -- login() itself is genuinely different from the rest of
// this file only in that it produces no data of its own to return on
// success.
export async function login(username: string, password: string): Promise<void> {
  await apiFetchOrThrow('/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logout(): Promise<void> {
  try {
    await apiFetch('/logout', { method: 'POST' })
  } catch {
    // A failed logout REQUEST (a real network error, not just a non-
    // 2xx response) must never prevent the caller's own UI-level
    // "log me out" intent from completing -- swallowed here. Unlike
    // the earlier, localStorage-based version of this function, there
    // is no longer any LOCAL cleanup step this needs to guarantee
    // regardless (the cookies themselves are only ever cleared by the
    // backend's own response, which never arrived if this branch
    // runs) -- App.jsx's own handleLogout() still needs to update its
    // OWN, local isLoggedIn state unconditionally, though, which is
    // why this still swallows rather than lets the error propagate:
    // the person asked to log out, and the UI should reflect that
    // immediately regardless of a transient network failure.
  }
}

// Deliberately returns the raw Response, not throwing on non-2xx --
// /query has FOUR meaningfully different outcomes (200 answer, 202
// pending write, 409 permissions changed, 401 session expired), and
// the caller needs to branch on the status itself, not just get a
// generic failure.
export async function query(queryText: string): Promise<Response> {
  return apiFetch('/query', {
    method: 'POST',
    body: JSON.stringify({ query: queryText }),
  })
}

export async function confirmWrite(writeId: string, approved: boolean): Promise<unknown> {
  const response = await apiFetchOrThrow(`/writes/${writeId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ approved }),
  })
  return response.json()
}

/** One proposal waiting for this user to decide on it.
 *
 * DELIBERATELY WITHOUT THE CHANGED VALUES. A pending write names object
 * ids and the fields it would set, both governed by MAC and
 * field-level RBAC on every other read path -- returning them because
 * the caller holds an execute grant would be a way around the read
 * rules. The server enforces this; the type says so, so a component
 * cannot be written expecting values that will never arrive.
 */
export interface AwaitingWrite {
  write_id: string
  action_type_name: string
  description: string
  proposed_by: string
  proposed_at: string
  object_count: number
  expires_at: string
  /** Both can be true: a deployment with no four-eyes rule lets
   *  someone approve their own write, and showing one flag would
   *  misreport the other. */
  awaiting_your_review: boolean
  proposed_by_you: boolean
  /** Fields the ontology no longer declares, as "Type.field".
   *
   *  Non-empty means this write CANNOT be approved -- the
   *  configuration moved on while it waited. A different state from
   *  rejected: rejected means a human decided against it, this means
   *  nobody can act on it either way.
   */
  undeclared_fields: string[]
  /** How many OTHER pending writes propose exactly this change.
   *
   *  Surfaced rather than prevented: a second identical proposal might
   *  be a double-click, a colleague re-requesting something forgotten,
   *  or a deliberate nudge, and the server cannot tell which. What was
   *  wrong was identical rows being indistinguishable.
   */
  duplicate_count: number
  /** How many individual changes this request makes.
   *
   *  A bulk action naming fifty objects is fifty tasks, and a
   *  reviewer may be eligible for some and not others. */
  tasks_total: number
  /** How many of them THIS reviewer may decide.
   *
   *  Fewer than tasks_total when a request spans security
   *  partitions: approving then covers this reviewer's share and
   *  leaves the rest for someone who can see them. Without this
   *  number, Approve looks like it runs the whole write. */
  tasks_you_may_decide: number
  /** How many have been approved, by anyone.
   *
   *  APPROVED, not decided: a rejected task is not progress toward
   *  invocation, so showing it as such would make a permanently
   *  blocked request look nearly ready. */
  tasks_approved: number
}

/** Proposals this user may decide on, oldest first.
 *
 * Before this existed, confirming a write required knowing its id --
 * which only the proposer had. Four-eyes was enforceable and
 * unreachable: the one person who could find a write was the one
 * person forbidden to approve it.
 */
export async function getAwaitingWrites(): Promise<AwaitingWrite[]> {
  const response = await apiFetchOrThrow('/writes/awaiting')
  return response.json() as Promise<AwaitingWrite[]>
}

/** One field a pending write would change.
 *
 * `readable` false means the reviewer lacks the read grant for it, and
 * both values are null as a REDACTION rather than because the data is
 * null. The distinction matters in a diff: a reviewer deciding on a
 * change needs to know the difference between "this becomes empty" and
 * "you may not see this".
 */
export interface FieldChange {
  field_name: string
  readable: boolean
  current_value: unknown
  proposed_value: unknown
}

export interface ObjectChange {
  object_type: string
  object_id: string
  operation: string
  changes: FieldChange[]
}

export interface WriteDetailResponse {
  write_id: string
  action_type_name: string
  description: string
  proposed_by: string
  proposed_at: string
  expires_at: string
  awaiting_your_review: boolean
  proposed_by_you: boolean
  objects: ObjectChange[]
  has_redacted_fields: boolean
}

/** What a pending write would actually change.
 *
 * SEPARATE FROM THE LISTING, because a diff needs the current value of
 * every changed field -- a permission-checked read per field per
 * object. Fetched when a reviewer opens a row, not for every row of a
 * queue they are scanning.
 */
export async function getWriteDetail(writeId: string): Promise<WriteDetailResponse> {
  const response = await apiFetchOrThrow(`/writes/${writeId}`)
  return response.json() as Promise<WriteDetailResponse>
}

// How current the data being read actually is. A deployment-wide fact,
// identical for every caller -- see api/routes.py's own
// data_freshness_route() for why it is its own endpoint rather than a
// field on /me. Requires a login but no particular grant, so anyone
// about to approve a write can see how fresh what they are approving
// against actually is.
export interface DataFreshness {
  source: 'live' | 'mirror'
  last_synced_at: string | null
}

export async function getDataFreshness(): Promise<DataFreshness> {
  const response = await apiFetchOrThrow('/data-freshness')
  return response.json() as Promise<DataFreshness>
}

// --- Admin: account management, all gated server-side by manage:users.
// This module never checks "is the current user an admin" itself --
// that's the backend's job (see api/routes.py's _require_manage_users());
// a non-admin calling any of these simply gets a real 403 from the
// server, surfaced the same way as any other ApiError.

export async function listUsers(): Promise<unknown> {
  const response = await apiFetchOrThrow('/users')
  return response.json()
}

export async function createUser(
  username: string,
  password: string,
  macValue: string,
  roleName: string,
): Promise<unknown> {
  const response = await apiFetchOrThrow('/users', {
    method: 'POST',
    body: JSON.stringify({
      username,
      password,
      mac_value: macValue || null,
      role_name: roleName,
    }),
  })
  return response.json()
}

export async function disableUser(username: string): Promise<void> {
  await apiFetchOrThrow(`/users/${username}/disable`, { method: 'POST' })
}

export async function enableUser(username: string): Promise<void> {
  await apiFetchOrThrow(`/users/${username}/enable`, { method: 'POST' })
}

export async function deleteUser(username: string): Promise<void> {
  await apiFetchOrThrow(`/users/${username}`, { method: 'DELETE' })
}

export async function logoutAllForUser(username: string): Promise<void> {
  await apiFetchOrThrow(`/users/${username}/logout-all`, { method: 'POST' })
}

export async function getVisibleSchema(username: string): Promise<unknown> {
  const response = await apiFetchOrThrow(`/users/${username}/visible-schema`)
  return response.json()
}

// A real "who am I" endpoint -- confirmed directly against how
// established identity platforms do this (OpenID Connect's own
// UserInfo endpoint; Palantir Foundry's own real, documented GET
// .../admin/users/getCurrent) before adding it, not invented from
// scratch. Server-side, the response carries Cache-Control: no-store
// (see api/routes.py's own _no_store dependency) -- session-specific
// data a shared browser or intermediate cache must never persist and
// later hand back to a different person on the same machine.
export async function getCurrentUser(): Promise<unknown> {
  const response = await apiFetchOrThrow('/me')
  return response.json()
}

// --- Browse/search: self-service, no manage:users needed -- every
// call here reflects the CURRENT logged-in user's own view/grants,
// enforced entirely server-side (see api/routes.py's own docstrings
// for both routes).

export async function getMyVisibleSchema(): Promise<unknown> {
  const response = await apiFetchOrThrow('/me/visible-schema')
  return response.json()
}

export async function getVisibleApps(): Promise<unknown> {
  const response = await apiFetchOrThrow('/me/visible-apps')
  return response.json()
}

export interface SearchOptions {
  /** Opaque. Comes from a previous response's next_page_token and is
   *  never constructed here -- the server encodes what it needs and
   *  the shape is its business. */
  pageToken?: string
  pageSize?: number
  /** "field" or "field:desc". The server validates the field against
   *  what this caller may read. */
  orderBy?: string
  /** Structured filters, ANDed with the text query. Two contexts
   *  combined: the text decides what MATCHES, these decide what is
   *  ELIGIBLE. It is what lets a chart click and a search box narrow
   *  the same object set. */
  conditions?: unknown[]
}

export async function searchObjects(
  objectType: string,
  queryText: string,
  options: SearchOptions = {},
): Promise<unknown> {
  const params = new URLSearchParams({ q: queryText })
  // Omitted rather than sent empty: the server has defaults, and
  // sending page_size="" would make it parse and reject a value the
  // caller never chose.
  if (options.pageToken) params.set('page_token', options.pageToken)
  if (options.pageSize) params.set('page_size', String(options.pageSize))
  if (options.orderBy) params.set('order_by', options.orderBy)
  if (options.conditions?.length) {
    params.set('conditions', JSON.stringify(options.conditions))
  }
  const response = await apiFetchOrThrow(`/objects/${objectType}/search?${params}`)
  return response.json()
}

/** Every id the current filter matches, for "select all matching".
 *
 * IDS, NOT A FILTER PASSED ONWARD. Foundry's approvals model settles
 * the design: "a task is an individual change in Foundry. All tasks
 * associated with a request must be approved for the request to be
 * invoked." A reviewer approves specific changes, never a rule to be
 * resolved later -- so the filter is resolved at SELECTION time and
 * what travels onward is the list it produced.
 *
 * Refused by the server above its bulk ceiling rather than truncated,
 * so a caller never receives a selection that silently omits part of
 * what it asked for.
 */
export async function matchingIds(objectType: string, queryText: string, conditions?: unknown[]): Promise<string[]> {
  const params = new URLSearchParams({ q: queryText })
  if (conditions?.length) params.set('conditions', JSON.stringify(conditions))
  const response = await apiFetchOrThrow(`/objects/${objectType}/matching-ids?${params}`)
  const body = (await response.json()) as { object_ids: string[] }
  return body.object_ids
}

/** RED metrics over a recent window, for the admin screen.
 *
 * Gated on manage:deployment by the server -- request timings say
 * which routes are used and how often, which is more than an ordinary
 * user should see about everyone else.
 */
/** One table's state in the mirror. */
export interface MirrorTableState {
  silo: string
  table: string
  last_synced_at: string | null
  /** Rows in the TYPED layer, which is what Elysium reads. */
  silver_rows: number | null
  /** Rows in the RAW layer, which takes whatever the source gave.
   *
   *  A DIVERGENCE FROM silver_rows IS THE DRIFT STATE: bronze took the
   *  new rows, silver refused to interpret them, and the gap is what a
   *  refused sync looks like from outside. */
  bronze_rows: number | null
  /** When the last sync ATTEMPT ran, as distinct from when the data
   *  last changed.
   *
   *  Snapshots record change, so a sync that ran and was REFUSED
   *  leaves exactly what a sync that ran and found nothing leaves.
   *  One is an incident; the other is Tuesday. */
  last_attempt_at: string | null
  /** 'synced' or 'refused'. Null when nothing has been recorded --
   *  which on an existing deployment means no sync has run since
   *  attempts began being kept. */
  last_attempt_outcome: string | null
  /** Why it was refused, in full. A reader who sees a refusal wants
   *  the column and the value, not a category. */
  last_attempt_detail: string | null
  /** When the data changed, newest first. Iceberg keeps a snapshot
   *  per commit, so this is history the mirror already holds. */
  snapshots?: MirrorSnapshot[]
}

/** One point the mirror could be rolled back to. */
export interface MirrorSnapshot {
  at: string
  operation: string
  rows: number | null
  current: boolean
}

export interface MirrorState {
  reading_from_mirror: boolean
  tables: MirrorTableState[]
  problems: string[]
}

export interface ServerSavedView {
  view_id: string
  name: string
  object_type: string
  query_text: string
  conditions: Array<Record<string, unknown>>
  presentation: Record<string, unknown>
  created_at: string
}

export async function getSavedViews(): Promise<ServerSavedView[]> {
  const response = await apiFetchOrThrow('/saved-views')
  return (await response.json()).views as ServerSavedView[]
}

export async function saveSavedView(body: {
  name: string
  object_type: string
  query_text?: string
  conditions?: Array<Record<string, unknown>>
  presentation?: Record<string, unknown>
}): Promise<string> {
  const response = await apiFetchOrThrow('/saved-views', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()).view_id as string
}

export async function deleteSavedView(viewId: string): Promise<void> {
  await apiFetchOrThrow(`/saved-views/${encodeURIComponent(viewId)}`, {
    method: 'DELETE',
  })
}

export interface Trigger {
  trigger_id: string
  name: string
  view_id: string
  above: number | null
  gained: number | null
  fell: number | null
  enabled: boolean
  created_at: string
  action_type?: string | null
  recipient_roles?: string[]
}

export async function getTriggers(): Promise<Trigger[]> {
  const response = await apiFetchOrThrow('/triggers')
  return (await response.json()).triggers as Trigger[]
}

export async function createTrigger(body: {
  name: string
  view_id: string
  above?: number | null
  gained?: number | null
  fell?: number | null
  action_type?: string | null
  action_parameter?: string | null
  action_values?: Record<string, unknown>
  recipient_roles?: string[]
}): Promise<string> {
  const response = await apiFetchOrThrow('/triggers', {
    method: 'POST',
    body: JSON.stringify(body),
  })
  return (await response.json()).trigger_id as string
}

export async function setTriggerEnabled(triggerId: string, enabled: boolean): Promise<void> {
  await apiFetchOrThrow(`/triggers/${encodeURIComponent(triggerId)}/enabled?enabled=${enabled}`, { method: 'POST' })
}

export async function deleteTrigger(triggerId: string): Promise<void> {
  await apiFetchOrThrow(`/triggers/${encodeURIComponent(triggerId)}`, {
    method: 'DELETE',
  })
}

export interface Notification {
  notification_id: string
  created_at: string
  kind: string
  summary: string
  detail: string | null
  seen: boolean
}

export async function getNotifications(): Promise<{
  notifications: Notification[]
  unseen: number
}> {
  const response = await apiFetchOrThrow('/notifications')
  return response.json() as Promise<{ notifications: Notification[]; unseen: number }>
}

export async function markNotificationSeen(notificationId: string): Promise<void> {
  await apiFetchOrThrow(`/notifications/${encodeURIComponent(notificationId)}/seen`, {
    method: 'POST',
  })
}

export async function startMirrorSync(): Promise<{ started: boolean; detail: string }> {
  const response = await apiFetchOrThrow('/admin/mirror/sync', { method: 'POST' })
  return response.json() as Promise<{ started: boolean; detail: string }>
}

export async function getMirrorState(): Promise<MirrorState> {
  const response = await apiFetchOrThrow('/admin/mirror')
  return response.json() as Promise<MirrorState>
}

export async function getMetrics(windowSeconds?: number): Promise<unknown> {
  const params = windowSeconds === undefined ? '' : `?window_seconds=${windowSeconds}`
  const response = await apiFetchOrThrow(`/admin/metrics${params}`)
  return response.json()
}

export interface LinkCount {
  target: string
  count: number
  cardinality?: string | null
}

/** How far each link from this object leads, before following any.
 *
 * COUNTS BEFORE EXPANSION: a person deciding whether to follow a link
 * needs to know it leads to four things or four thousand before they
 * commit. Every count is what THIS caller would receive, so it cannot
 * disagree with the expansion that follows.
 */
export async function getLinkCounts(objectType: string, objectId: string): Promise<Record<string, LinkCount>> {
  // encodeURIComponent for the same reason getObjectDetail does it: an
  // id is DATA, and one containing a literal "/" would otherwise split
  // the URL path.
  const response = await apiFetchOrThrow(`/objects/${objectType}/${encodeURIComponent(objectId)}/link-counts`)
  const body = (await response.json()) as { links?: Record<string, LinkCount> }
  return body.links ?? {}
}

export async function getObjectDetail(objectType: string, objectId: string): Promise<unknown> {
  // objectId, unlike objectType, is genuinely DATA-derived (a real
  // customer_id, a real integer transaction id, ...) rather than a
  // fixed, schema-controlled name -- encoded specifically because an
  // id containing a literal "/" would otherwise split the URL path
  // in a way the backend's own path routing was never meant to parse.
  const response = await apiFetchOrThrow(`/objects/${objectType}/${encodeURIComponent(objectId)}`)
  return response.json()
}

// --- Stage 3: direct action invocation, no LLM involved. Mirrors
// getMyVisibleSchema()'s own self-service pattern exactly.

// Cached, because two components need this and neither should pay for
// the other's copy: ObjectDetailPanel (to offer actions on an object)
// and app-schema's ActionTypes tab. Both previously fetched
// independently, so opening one then the other fetched twice.
//
// Cached HERE rather than in either component, so a third consumer
// gets the sharing for free instead of inventing a third cache. The
// contents change only when the deployment's YAML does, so a reload
// picking up a change is the same freshness every other schema read
// in this app has.
// The PROMISE is cached, not the result.
//
// Caching the result was a check-then-act: two callers both see null,
// both await, and the value only exists after the second has already
// started its own request. A real log showed two requests for one
// object-detail page plus one schema tab, which is exactly that race
// -- and StrictMode double-invoking effects means even ONE component
// can hit it alone.
//
// Storing the in-flight promise means the second caller awaits the
// first's request instead of starting another. The same fix as the
// backend's security cache, in a different language: the failure is
// not "the cache is wrong", it is "two callers raced to fill it".
let cachedActionTypes: Promise<unknown> | null = null

/** Clears the cache. For tests, which would otherwise share it. */
export function resetVisibleActionTypesCache(): void {
  cachedActionTypes = null
}

export function getVisibleActionTypesCached(): Promise<unknown> {
  if (cachedActionTypes === null) {
    // A FAILED request must not be cached, or one network blip makes
    // action types permanently unavailable for the session.
    cachedActionTypes = getVisibleActionTypes().catch((error: unknown) => {
      cachedActionTypes = null
      throw error
    })
  }
  return cachedActionTypes
}

export interface AggregateBody {
  /** The object set to aggregate over, as filter conditions. */
  conditions?: unknown[]
  /** count, sum, avg, min or max. */
  aggregate: string
  /** The field to aggregate. Omitted for count, which needs none. */
  field?: string
  /** Bucket by this field. Omitted for a single statistic over the
   *  whole set. */
  group_by?: string
}

export async function aggregateObjects(objectType: string, body: AggregateBody): Promise<unknown> {
  const response = await apiFetchOrThrow(`/objects/${objectType}/aggregate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  return response.json()
}

export async function getRequestTrace(requestId: string): Promise<unknown> {
  const response = await apiFetchOrThrow(`/requests/${encodeURIComponent(requestId)}/trace`)
  return response.json()
}

export async function getObjectNotes(objectType: string, objectId: string): Promise<unknown> {
  const response = await apiFetchOrThrow(`/objects/${objectType}/${encodeURIComponent(objectId)}/notes`)
  return response.json()
}

export async function createObjectNote(objectType: string, objectId: string, text: string): Promise<unknown> {
  const response = await apiFetchOrThrow(`/objects/${objectType}/${encodeURIComponent(objectId)}/notes`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  return response.json()
}

export async function getObjectHistory(objectType: string, objectId: string): Promise<unknown> {
  const response = await apiFetchOrThrow(`/objects/${objectType}/${encodeURIComponent(objectId)}/history`)
  return response.json()
}

export async function getSilos(): Promise<unknown> {
  const response = await apiFetchOrThrow('/silos')
  return response.json()
}

export async function getDeploymentConfig(): Promise<unknown> {
  const response = await apiFetchOrThrow('/config')
  return response.json()
}

export async function getVisibleActionTypes(): Promise<unknown> {
  const response = await apiFetchOrThrow('/me/visible-action-types')
  return response.json()
}

export async function proposeAction(actionTypeName: string, parameters: Record<string, unknown>): Promise<unknown> {
  // actionTypeName is a fixed, schema-controlled name (like
  // objectType above), never encoded -- only objectId-shaped, DATA-
  // derived values get that treatment (see getObjectDetail() above).
  const response = await apiFetchOrThrow(`/actions/${actionTypeName}`, {
    method: 'POST',
    body: JSON.stringify({ parameters }),
  })
  return response.json()
}
