// api.js  (the ONE place that knows about fetch, the session/CSRF
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

export class ApiError extends Error {
  constructor(status, message) {
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
//   setError(err.message)   // or whatever this call site does otherwise
//
// Deliberately narrow -- extracts ONLY the part that was genuinely
// identical everywhere. The surrounding try/catch/finally shape still
// varies per call site (different success-path state, different
// finally cleanup), and folding THAT into a generic "run this and
// handle errors" wrapper too would trade real, if repetitive, clarity
// at each call site for a more abstract, harder-to-follow one -- not
// attempted here for that reason, not an oversight.
export function handleIfSessionExpired(err, onSessionExpired) {
  if (err instanceof ApiError && err.status === 401) {
    onSessionExpired()
    return true
  }
  return false
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
function getCsrfCookie() {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE_NAME}=([^;]*)`))
  return match ? decodeURIComponent(match[1]) : null
}

async function apiFetch(path, options = {}) {
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
    if (csrfToken) headers[CSRF_HEADER_NAME] = csrfToken
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
  return fetch(`/api${path}`, { ...options, headers, credentials: 'same-origin' })
}

// Throws ApiError on any non-2xx response -- used by calls where the
// caller only cares about success/failure, not the raw status (login,
// confirming a write). query() is deliberately DIFFERENT -- see below.
async function apiFetchOrThrow(path, options = {}) {
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
export async function login(username, password) {
  await apiFetchOrThrow('/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
}

export async function logout() {
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
export async function query(queryText) {
  return apiFetch('/query', {
    method: 'POST',
    body: JSON.stringify({ query: queryText }),
  })
}

export async function confirmWrite(writeId, approved) {
  const response = await apiFetchOrThrow(`/writes/${writeId}/confirm`, {
    method: 'POST',
    body: JSON.stringify({ approved }),
  })
  return response.json()
}

// --- Admin: account management, all gated server-side by manage:users.
// This module never checks "is the current user an admin" itself --
// that's the backend's job (see api/routes.py's _require_manage_users());
// a non-admin calling any of these simply gets a real 403 from the
// server, surfaced the same way as any other ApiError.

export async function listUsers() {
  const response = await apiFetchOrThrow('/users')
  return response.json()
}

export async function createUser(username, password, macValue, roleName) {
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

export async function disableUser(username) {
  await apiFetchOrThrow(`/users/${username}/disable`, { method: 'POST' })
}

export async function enableUser(username) {
  await apiFetchOrThrow(`/users/${username}/enable`, { method: 'POST' })
}

export async function deleteUser(username) {
  await apiFetchOrThrow(`/users/${username}`, { method: 'DELETE' })
}

export async function logoutAllForUser(username) {
  await apiFetchOrThrow(`/users/${username}/logout-all`, { method: 'POST' })
}

export async function getVisibleSchema(username) {
  const response = await apiFetchOrThrow(`/users/${username}/visible-schema`)
  return response.json()
}

// --- Browse/search: self-service, no manage:users needed -- every
// call here reflects the CURRENT logged-in user's own view/grants,
// enforced entirely server-side (see api/routes.py's own docstrings
// for both routes).

export async function getMyVisibleSchema() {
  const response = await apiFetchOrThrow('/me/visible-schema')
  return response.json()
}

export async function getVisibleApps() {
  const response = await apiFetchOrThrow('/me/visible-apps')
  return response.json()
}

export async function searchObjects(objectType, queryText) {
  const params = new URLSearchParams({ q: queryText })
  const response = await apiFetchOrThrow(`/objects/${objectType}/search?${params}`)
  return response.json()
}

export async function getObjectDetail(objectType, objectId) {
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

export async function getVisibleActionTypes() {
  const response = await apiFetchOrThrow('/me/visible-action-types')
  return response.json()
}

export async function proposeAction(actionTypeName, parameters) {
  // actionTypeName is a fixed, schema-controlled name (like
  // objectType above), never encoded -- only objectId-shaped, DATA-
  // derived values get that treatment (see getObjectDetail() above).
  const response = await apiFetchOrThrow(`/actions/${actionTypeName}`, {
    method: 'POST',
    body: JSON.stringify({ parameters }),
  })
  return response.json()
}
