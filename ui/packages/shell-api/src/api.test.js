import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  ApiError,
  login,
  logout,
  query,
  confirmWrite,
  listUsers,
  createUser,
  disableUser,
  enableUser,
  deleteUser,
  logoutAllForUser,
  getVisibleSchema,
  getMyVisibleSchema,
  getVisibleApps,
  searchObjects,
  getObjectDetail,
  getVisibleActionTypes,
  proposeAction,
  handleIfSessionExpired,
} from './api'

function jsonResponse(body, { ok = true, status = ok ? 200 : 400 } = {}) {
  return {
    ok,
    status,
    json: async () => body,
  }
}

// The real session token no longer lives in anything this file can
// see or set at all -- it's a genuine httponly cookie now, invisible
// to JavaScript by design (see api.js's own header comment). Only
// elysium_csrf is ever read here, matching what api.js itself can
// actually access.
function setCsrfCookie(value) {
  document.cookie = `elysium_csrf=${value}`
}

function clearCsrfCookie() {
  document.cookie = 'elysium_csrf=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/'
}

beforeEach(() => {
  clearCsrfCookie()
  global.fetch = vi.fn()
})

afterEach(() => {
  vi.restoreAllMocks()
})

// The SHARED mechanism every other export in this file funnels
// through -- tested thoroughly, once, here. A bug in this layer would
// silently affect every single caller, so this gets real depth;
// individual thin-wrapper exports get a lighter, table-driven check
// further down instead of 15+ near-identical hand-written tests.
describe('apiFetch / apiFetchOrThrow (via real exported callers)', () => {
  it('prefixes every request with /api', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await login('alice', 'pw')
    expect(global.fetch).toHaveBeenCalledWith('/api/login', expect.anything())
  })

  it('always sends Content-Type: application/json', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await login('alice', 'pw')
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['Content-Type']).toBe('application/json')
  })

  it('always sets credentials: same-origin -- this is what makes the real, httponly session cookie get sent at all', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await getMyVisibleSchema()
    const [, options] = global.fetch.mock.calls[0]
    expect(options.credentials).toBe('same-origin')
  })

  it('attaches a real X-CSRF-Token header, read from the elysium_csrf cookie, on a state-changing request', async () => {
    setCsrfCookie('real-csrf-value')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await confirmWrite('w1', true)
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBe('real-csrf-value')
  })

  it('sends no X-CSRF-Token header at all when no elysium_csrf cookie exists yet', async () => {
    // The real, normal case for login() itself -- no session/CSRF
    // cookie pair exists yet at the moment someone is logging in.
    global.fetch.mockResolvedValue(jsonResponse({}))
    await login('alice', 'pw')
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBeUndefined()
  })

  it("never attaches X-CSRF-Token on a GET request, even when the cookie exists -- matches the backend's own safe-method exemption", async () => {
    setCsrfCookie('real-csrf-value')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await getMyVisibleSchema()
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBeUndefined()
  })

  it('correctly decodes a URL-encoded CSRF cookie value, not just a plain one', async () => {
    // The real, backend-generated value (secrets.token_urlsafe()) is
    // always already URL-safe in practice, so this never actually
    // matters for the real cookie this app sets -- but getCsrfCookie()
    // still genuinely calls decodeURIComponent() on whatever it reads,
    // and every other test's own plain values (e.g. 'real-csrf-value')
    // decode identically to themselves either way, so none of them
    // would catch a real regression here (a broken/removed decode
    // call). This uses a value that only reads correctly if decoding
    // genuinely happened.
    document.cookie = 'elysium_csrf=hello%20world'
    global.fetch.mockResolvedValue(jsonResponse({}))
    await confirmWrite('w1', true)
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBe('hello world')
  })

  it('correctly extracts elysium_csrf when other, unrelated cookies are also present', async () => {
    document.cookie = 'unrelated_cookie=abc'
    document.cookie = 'elysium_csrf=real-value'
    document.cookie = 'another_cookie=xyz'
    global.fetch.mockResolvedValue(jsonResponse({}))
    await confirmWrite('w1', true)
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBe('real-value')
  })

  it("throws ApiError with the real status and the backend's own detail message on failure", async () => {
    global.fetch.mockResolvedValue(jsonResponse({ detail: 'Invalid username or password' }, { ok: false, status: 401 }))
    await expect(login('alice', 'wrong')).rejects.toMatchObject({
      status: 401,
      message: 'Invalid username or password',
    })
  })

  it('throws ApiError as a real instance of ApiError, not a plain object', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ detail: 'nope' }, { ok: false, status: 403 }))
    await expect(login('alice', 'wrong')).rejects.toBeInstanceOf(ApiError)
  })

  it('falls back to a generic message when the error body is not valid JSON', async () => {
    global.fetch.mockResolvedValue({
      ok: false,
      status: 500,
      json: async () => {
        throw new Error('not json')
      },
    })
    await expect(login('alice', 'pw')).rejects.toMatchObject({
      status: 500,
      message: 'Request failed (500)',
    })
  })
})

// The ONE shared "is this a session-expiry error, and if so, handle
// it" helper, replacing what used to be nine separate, byte-for-byte
// identical checks across nine different call sites in this app --
// tested directly, thoroughly, here, since it's now genuinely shared,
// important logic, not indirectly covered only through whichever
// component happens to call it.
describe('handleIfSessionExpired', () => {
  it('calls onSessionExpired and returns true for a real 401 ApiError', () => {
    const onSessionExpired = vi.fn()
    const result = handleIfSessionExpired(new ApiError(401, 'session expired'), onSessionExpired)
    expect(onSessionExpired).toHaveBeenCalledTimes(1)
    expect(result).toBe(true)
  })

  it('does NOT call onSessionExpired for a non-401 ApiError, and returns false', () => {
    const onSessionExpired = vi.fn()
    const result = handleIfSessionExpired(new ApiError(403, 'forbidden'), onSessionExpired)
    expect(onSessionExpired).not.toHaveBeenCalled()
    expect(result).toBe(false)
  })

  it('does NOT call onSessionExpired for a plain Error that is not an ApiError, and returns false', () => {
    const onSessionExpired = vi.fn()
    const result = handleIfSessionExpired(new Error('network down'), onSessionExpired)
    expect(onSessionExpired).not.toHaveBeenCalled()
    expect(result).toBe(false)
  })

  it('does not call onSessionExpired for a 401-STATUS plain object that is not a real ApiError instance', () => {
    // Confirms the check is genuinely `instanceof ApiError`, not just
    // duck-typing on `.status === 401` -- a real, meaningful
    // distinction: only OUR OWN api.js ever constructs a real
    // ApiError, so this can't be spoofed by some other error shape
    // that happens to carry a matching status field.
    const onSessionExpired = vi.fn()
    const result = handleIfSessionExpired({ status: 401, message: 'looks like one but is not' }, onSessionExpired)
    expect(onSessionExpired).not.toHaveBeenCalled()
    expect(result).toBe(false)
  })
})

// No token/cookie assertions here at all anymore -- the real session
// and CSRF cookies are set/cleared entirely by the BACKEND's own
// Set-Cookie response headers (core/auth/auth_cookies.py), invisible
// to and unmanaged by this file. What's left to genuinely test here
// is login()/logout()'s own real behavior: does login() throw
// correctly on failure and return nothing on success; does logout()
// swallow a network-level failure without letting it propagate.
describe('login/logout', () => {
  it('login resolves with no value on a successful response', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await expect(login('alice', 'correct-pw')).resolves.toBeUndefined()
  })

  it('login throws a real ApiError on a failed response, same as any other apiFetchOrThrow caller', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ detail: 'Invalid username or password' }, { ok: false, status: 401 }))
    await expect(login('alice', 'wrong-pw')).rejects.toBeInstanceOf(ApiError)
  })

  it('logout swallows a network-level failure rather than letting it propagate', async () => {
    // A real bug this project actually had, found by a real test
    // (see git history): a network failure during logout must never
    // prevent the caller's own "log me out" UI intent from completing
    // -- App.jsx's own handleLogout() still needs to update its local
    // isLoggedIn state unconditionally afterward. There is no longer
    // any LOCAL cleanup step this needs to guarantee either way (the
    // cookies themselves are managed entirely by the backend's own
    // response), but logout() itself must still never throw.
    global.fetch.mockRejectedValue(new Error('network down'))
    await expect(logout()).resolves.toBeUndefined()
  })

  it('logout resolves normally on a real, successful request too', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await expect(logout()).resolves.toBeUndefined()
  })

  it('logout attaches the X-CSRF-Token header, same as any other state-changing call', async () => {
    setCsrfCookie('real-csrf-value')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await logout()
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['X-CSRF-Token']).toBe('real-csrf-value')
  })
})

describe('query() -- deliberately does NOT throw on a non-2xx status', () => {
  it('returns the raw Response even for a 409 (permissions changed mid-query)', async () => {
    const fakeResponse = jsonResponse({ detail: 'permissions changed' }, { ok: false, status: 409 })
    global.fetch.mockResolvedValue(fakeResponse)
    const result = await query('how many customers do we have?')
    expect(result).toBe(fakeResponse)
    expect(result.ok).toBe(false)
  })

  it('returns the raw Response for a normal 200 too', async () => {
    const fakeResponse = jsonResponse({ answer: '42' })
    global.fetch.mockResolvedValue(fakeResponse)
    const result = await query('how many customers do we have?')
    expect(result).toBe(fakeResponse)
  })
})

// Every OTHER exported function is a thin wrapper around
// apiFetchOrThrow with no real logic of its own beyond "hit this
// specific URL with this specific method." One table-driven check
// confirms each one is wired to the RIGHT endpoint -- catches a real,
// cheap-to-make mistake (a typo'd path, a copy-pasted wrong method)
// without 15+ separate, repetitive test functions for code that has
// no branching to get wrong.
describe('every remaining export hits the correct endpoint and method', () => {
  const cases = [
    { name: 'confirmWrite', call: () => confirmWrite('w1', true), path: '/api/writes/w1/confirm', method: 'POST' },
    { name: 'listUsers', call: () => listUsers(), path: '/api/users', method: undefined },
    {
      name: 'createUser',
      call: () => createUser('bob', 'pw', null, 'editor'),
      path: '/api/users',
      method: 'POST',
    },
    { name: 'disableUser', call: () => disableUser('bob'), path: '/api/users/bob/disable', method: 'POST' },
    { name: 'enableUser', call: () => enableUser('bob'), path: '/api/users/bob/enable', method: 'POST' },
    { name: 'deleteUser', call: () => deleteUser('bob'), path: '/api/users/bob', method: 'DELETE' },
    {
      name: 'logoutAllForUser',
      call: () => logoutAllForUser('bob'),
      path: '/api/users/bob/logout-all',
      method: 'POST',
    },
    {
      name: 'getVisibleSchema',
      call: () => getVisibleSchema('bob'),
      path: '/api/users/bob/visible-schema',
      method: undefined,
    },
    { name: 'getMyVisibleSchema', call: () => getMyVisibleSchema(), path: '/api/me/visible-schema', method: undefined },
    { name: 'getVisibleApps', call: () => getVisibleApps(), path: '/api/me/visible-apps', method: undefined },
    {
      name: 'searchObjects',
      call: () => searchObjects('Customer', 'ada'),
      path: '/api/objects/Customer/search?q=ada',
      method: undefined,
    },
    {
      name: 'getObjectDetail',
      call: () => getObjectDetail('Customer', 'cust_001'),
      path: '/api/objects/Customer/cust_001',
      method: undefined,
    },
    {
      name: 'getVisibleActionTypes',
      call: () => getVisibleActionTypes(),
      path: '/api/me/visible-action-types',
      method: undefined,
    },
    {
      name: 'proposeAction',
      call: () => proposeAction('UpdateCustomerName', { customer_id: 'cust_001', new_name: 'X' }),
      path: '/api/actions/UpdateCustomerName',
      method: 'POST',
    },
  ]

  it.each(cases)('$name hits $path with method $method', async ({ call, path, method }) => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await call()
    const [calledPath, options] = global.fetch.mock.calls[0]
    expect(calledPath).toBe(path)
    expect(options.method).toBe(method)
  })

  it('getObjectDetail encodes an id containing a slash, so it cannot split the URL path', async () => {
    global.fetch.mockResolvedValue(jsonResponse({}))
    await getObjectDetail('Customer', 'weird/id')
    const [calledPath] = global.fetch.mock.calls[0]
    expect(calledPath).toBe('/api/objects/Customer/weird%2Fid')
  })
})
