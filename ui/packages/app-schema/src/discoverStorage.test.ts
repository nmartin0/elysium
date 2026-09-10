import { describe, it, expect, beforeEach } from 'vitest'

import { getFavourites, getRecent, isFavourite, recordVisit, toggleFavourite } from './discoverStorage'

const ALL = ['Customer', 'Transaction', 'Account']

beforeEach(() => {
  window.localStorage.clear()
})

describe('recently viewed', () => {
  it('returns most recent first', () => {
    recordVisit('alice', 'Customer')
    recordVisit('alice', 'Transaction')

    expect(getRecent('alice', ALL)).toEqual(['Transaction', 'Customer'])
  })

  it('moves a revisited type to the front rather than duplicating it', () => {
    recordVisit('alice', 'Customer')
    recordVisit('alice', 'Transaction')
    recordVisit('alice', 'Customer')

    expect(getRecent('alice', ALL)).toEqual(['Customer', 'Transaction'])
  })

  it('keeps the list bounded', () => {
    for (let index = 0; index < 20; index += 1) {
      recordVisit('alice', `Type${index}`)
    }
    const visible = Array.from({ length: 20 }, (_, index) => `Type${index}`)

    expect(getRecent('alice', visible).length).toBeLessThanOrEqual(8)
  })
})

describe('per-username isolation', () => {
  it('does not show one user another user on the same browser', () => {
    // localStorage is per-BROWSER. Without keying by username, logging
    // out and back in as someone else inherits the first user's lists.
    recordVisit('alice', 'Customer')
    toggleFavourite('alice', 'Account')

    expect(getRecent('bob', ALL)).toEqual([])
    expect(getFavourites('bob', ALL)).toEqual([])
  })

  it('keeps both users lists intact', () => {
    recordVisit('alice', 'Customer')
    recordVisit('bob', 'Transaction')

    expect(getRecent('alice', ALL)).toEqual(['Customer'])
    expect(getRecent('bob', ALL)).toEqual(['Transaction'])
  })
})

describe('the schema is the authority', () => {
  it('hides a stored type the caller can no longer see', () => {
    // THE permission-change case. A user who loses read access still
    // has the name in their browser; it must silently stop appearing
    // rather than offering a type they cannot open.
    recordVisit('alice', 'Customer')
    toggleFavourite('alice', 'Customer')

    const afterLosingAccess = ['Transaction', 'Account']

    expect(getRecent('alice', afterLosingAccess)).toEqual([])
    expect(getFavourites('alice', afterLosingAccess)).toEqual([])
  })

  it('shows a newly granted type without any migration', () => {
    // The other direction. Nothing is reconciled against a cached
    // schema, so a gained grant takes effect on the next read --
    // because the stored name was never trusted in the first place.
    recordVisit('alice', 'Customer')

    expect(getRecent('alice', [])).toEqual([])
    expect(getRecent('alice', ['Customer'])).toEqual(['Customer'])
  })

  it('does not lose a stored name while access is absent', () => {
    // Filtered on READ, not pruned on write. A temporary loss of
    // access -- a role changed and changed back -- should not silently
    // erase someone's favourites.
    toggleFavourite('alice', 'Customer')

    expect(getFavourites('alice', [])).toEqual([])
    expect(getFavourites('alice', ALL)).toEqual(['Customer'])
  })
})

describe('favourites', () => {
  it('toggles on and off', () => {
    expect(toggleFavourite('alice', 'Customer')).toBe(true)
    expect(isFavourite('alice', 'Customer')).toBe(true)

    expect(toggleFavourite('alice', 'Customer')).toBe(false)
    expect(isFavourite('alice', 'Customer')).toBe(false)
  })
})

describe('degrading safely', () => {
  it('treats malformed storage as empty', () => {
    // Browser storage is editable by hand. A malformed value must not
    // break the page it decorates.
    window.localStorage.setItem('elysium.recent.alice', '{"not":"an array"}')

    expect(getRecent('alice', ALL)).toEqual([])
  })

  it('ignores non-string entries', () => {
    window.localStorage.setItem('elysium.favourites.alice', '["Customer", 42, null]')

    expect(getFavourites('alice', ALL)).toEqual(['Customer'])
  })
})
