// api.js  (the ONE place that knows about fetch, headers, the token,
// and the /api prefix)
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
// The /api prefix itself is load-bearing, not stylistic -- a real bug
// this project shipped without it: a client-side react-router-dom
// route and a real backend path were both /objects/{type}/{id}, so a
// raw browser navigation to a bookmarked Object View URL hit the
// backend directly (no auth header on a page navigation), instead of
// ever loading this app. See api/app.py's own include_router() call
// and vite.config.js's own AI-notes for the fuller history.
//
// The token lives in localStorage -- a real, standalone browser app,
// not a sandboxed artifact, so this is the correct, normal choice
// here (the restriction against browser storage applies specifically
// to Claude's artifact environment, not to a real deployed app like
// this one).

const TOKEN_KEY = 'elysium_token'

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

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}

function setToken(token) {
  localStorage.setItem(TOKEN_KEY, token)
}

function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
}

async function apiFetch(path, options = {}) {
  const token = getToken()
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  }
  // Every real backend path lives under /api -- see api/app.py's own
  // include_router() call for the full reasoning (a real, structural
  // guarantee that no client-side react-router-dom route can ever
  // collide with a real API path, found necessary by a real bug: a
  // bookmarked Object View URL that happened to match an unprefixed
  // backend path hit the backend directly on a raw page navigation,
  // with no auth header, instead of ever loading this app). This is
  // the ONE place that needs to know this -- every caller in this
  // file passes a plain, unprefixed path like '/login'.
  return fetch(`/api${path}`, { ...options, headers })
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

export async function login(username, password) {
  const response = await apiFetchOrThrow('/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  })
  const data = await response.json()
  setToken(data.token)
  return data
}

export async function logout() {
  try {
    await apiFetch('/logout', { method: 'POST' })
  } catch {
    // A failed logout REQUEST (a real network error, not just a non-
    // 2xx response) must never prevent the LOCAL logout from
    // completing -- swallowed here, not just left to a finally block.
    // A bug this project actually had, found by a real test: try/
    // finally clears the token below either way, but finally does
    // NOT swallow the original error -- it still re-throws after
    // running, which meant a network failure during logout would
    // propagate all the way up into App.jsx's own handleLogout(),
    // which never catches it, so setIsLoggedIn(false) would never
    // run. The token would be gone (so every subsequent API call
    // would fail auth) while the UI kept showing the logged-in view
    // regardless -- a genuinely confusing, broken state, not a
    // hypothetical one.
  } finally {
    clearToken()
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
