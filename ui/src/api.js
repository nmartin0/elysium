// api.js  (the ONE place that knows about fetch, headers, and the token)
//
// Relative paths throughout ("/login", not "http://localhost:8000/login")
// -- this works correctly in BOTH modes without any configuration:
// Vite's dev-server proxy (see vite.config.js) forwards them to the
// real backend during development, and the built app is served BY
// FastAPI itself in production (see api/app.py), so they're already
// same-origin there too. No environment variable, no base URL to get
// wrong between dev and prod.
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
  return fetch(path, { ...options, headers })
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
  } finally {
    // Cleared regardless of whether the request itself succeeded --
    // a failed logout call server-side shouldn't leave the browser
    // still holding onto (and offering to reuse) the token.
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

export async function searchObjects(objectType, queryText) {
  const params = new URLSearchParams({ q: queryText })
  const response = await apiFetchOrThrow(`/objects/${objectType}/search?${params}`)
  return response.json()
}
