/**
 * Noticing that the server's configuration moved.
 *
 * THE PROBLEM. The UI fetched a user's visible schema ONCE, at login,
 * and never again. A configuration reload changed what the server
 * would answer, and the browser went on believing what it was told.
 *
 * Found by using it: a field moved to `discover:` was correctly
 * withheld by the server, arriving as null, and rendered as "not set"
 * because the cached schema still called it readable. The right answer
 * only appeared after a manual browser refresh.
 *
 * NO POLLING. Every response carries the serving generation, so the
 * client notices on its NEXT request -- whatever that request is.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { forgetLastSeenGeneration, getCurrentUser, setGenerationChangeHandler } from './api'

function respondWith(generation: string | null) {
  const headers = new Headers()
  if (generation !== null) headers.set('x-elysium-generation', generation)
  return Promise.resolve(new Response(JSON.stringify({}), { status: 200, headers }))
}

let fetchMock: ReturnType<typeof vi.fn>

beforeEach(() => {
  forgetLastSeenGeneration()
  fetchMock = vi.fn()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => {
  vi.unstubAllGlobals()
  setGenerationChangeHandler(() => {})
})

describe('a configuration reload reaches the client', () => {
  it('fires when the generation changes', async () => {
    const onChange = vi.fn()
    setGenerationChangeHandler(onChange)

    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()
    fetchMock.mockReturnValueOnce(respondWith('8'))
    await getCurrentUser()

    expect(onChange).toHaveBeenCalledTimes(1)
  })

  it('does NOT fire on the first response', async () => {
    // The first establishes the baseline. Otherwise logging in would
    // immediately refetch what it had just fetched.
    const onChange = vi.fn()
    setGenerationChangeHandler(onChange)

    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()

    expect(onChange).not.toHaveBeenCalled()
  })

  it('does not fire when the generation is unchanged', async () => {
    // THE CONTROL. Firing on every response would refetch the schema
    // constantly -- worse than the staleness it replaces.
    const onChange = vi.fn()
    setGenerationChangeHandler(onChange)

    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()
    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()
    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()

    expect(onChange).not.toHaveBeenCalled()
  })

  it('treats an absent header as no news', async () => {
    // A static file, or a response from before this shipped, must not
    // look like a reload -- that would refetch on every page load.
    const onChange = vi.fn()
    setGenerationChangeHandler(onChange)

    fetchMock.mockReturnValueOnce(respondWith('7'))
    await getCurrentUser()
    fetchMock.mockReturnValueOnce(respondWith(null))
    await getCurrentUser()

    expect(onChange).not.toHaveBeenCalled()
  })

  it('does not break a call when the response has no headers at all', async () => {
    // Runs on EVERY call, so a throw here would fail requests that
    // were otherwise fine. Thirty-four tests failed this way before
    // the guard went in.
    setGenerationChangeHandler(vi.fn())
    fetchMock.mockReturnValueOnce(Promise.resolve({ ok: true, json: async () => ({}) }))

    await expect(getCurrentUser()).resolves.toBeDefined()
  })
})
