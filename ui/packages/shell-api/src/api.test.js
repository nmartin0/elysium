import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import {
  ApiError,
  getToken,
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

beforeEach(() => {
  localStorage.clear()
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
    global.fetch.mockResolvedValue(jsonResponse({ token: 't', role: 'editor' }))
    await login('alice', 'pw')
    expect(global.fetch).toHaveBeenCalledWith('/api/login', expect.anything())
  })

  it('always sends Content-Type: application/json', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ token: 't', role: 'editor' }))
    await login('alice', 'pw')
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers['Content-Type']).toBe('application/json')
  })

  it('attaches a real Authorization header when a token is stored', async () => {
    localStorage.setItem('elysium_token', 'real-token-123')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await getMyVisibleSchema()
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers.Authorization).toBe('Bearer real-token-123')
  })

  it('sends no Authorization header at all when no token is stored', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ token: 't', role: 'editor' }))
    await login('alice', 'pw')
    const [, options] = global.fetch.mock.calls[0]
    expect(options.headers.Authorization).toBeUndefined()
  })

  it('throws ApiError with the real status and the backend\'s own detail message on failure', async () => {
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

describe('login/logout token lifecycle', () => {
  it('login stores the real token returned by the backend', async () => {
    global.fetch.mockResolvedValue(jsonResponse({ token: 'brand-new-token', role: 'editor' }))
    await login('alice', 'correct-pw')
    expect(getToken()).toBe('brand-new-token')
  })

  it('logout clears the token even when the request itself fails', async () => {
    localStorage.setItem('elysium_token', 'stale-token')
    global.fetch.mockRejectedValue(new Error('network down'))
    await logout()
    expect(getToken()).toBeNull()
  })

  it('logout clears the token on a normal, successful request too', async () => {
    localStorage.setItem('elysium_token', 'stale-token')
    global.fetch.mockResolvedValue(jsonResponse({}))
    await logout()
    expect(getToken()).toBeNull()
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
