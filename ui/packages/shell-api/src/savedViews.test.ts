/**
 * A saved view is a URL and a name.
 *
 * Nothing more, because Browse's view state already lives in the query
 * string. Persisting one is storing a string rather than designing a
 * schema that would need revising every time a panel gained a knob.
 *
 * PERSONAL, NOT SHARED. Sharing a view is already solved -- send the
 * link. This answers the other question: "the thing I set up on
 * Tuesday, where did it go". That is one person's memory, so there is
 * no permission model here and no server store.
 */

import { beforeEach, describe, expect, it } from 'vitest'

import { writePreference } from './browserPreferences'
import { deleteView, listSavedViews, saveView } from './savedViews'

const USER = 'alice'

beforeEach(() => window.localStorage.clear())

describe('savedViews', () => {
  it('starts empty', () => {
    expect(listSavedViews(USER)).toEqual([])
  })

  it('keeps the name the person chose', () => {
    // Their words, not a generated summary. "Q3 refunds to chase"
    // means something no derived title would.
    saveView(USER, 'Q3 refunds to chase', '/browse?type=Transaction&q=refund')

    expect(listSavedViews(USER)[0]?.name).toBe('Q3 refunds to chase')
  })

  it('keeps the URL exactly', () => {
    const url = '/browse?type=Transaction&q=refund&filters=%5B%5D'
    saveView(USER, 'refunds', url)

    expect(listSavedViews(USER)[0]?.url).toBe(url)
  })

  it('lists the newest first', () => {
    saveView(USER, 'older', '/browse?type=A')
    saveView(USER, 'newer', '/browse?type=B')

    expect(listSavedViews(USER).map((view) => view.name)).toEqual(['newer', 'older'])
  })

  it('replaces a view saved under the same name', () => {
    // How a person UPDATES a view: they changed a filter and want the
    // name to mean the new thing. Two entries with one name would make
    // the list unusable and leave no way to correct it.
    saveView(USER, 'refunds', '/browse?type=Transaction')
    saveView(USER, 'refunds', '/browse?type=Transaction&q=late')

    const views = listSavedViews(USER)
    expect(views).toHaveLength(1)
    expect(views[0]?.url).toBe('/browse?type=Transaction&q=late')
  })

  it('refuses a blank name rather than saving an unfindable view', () => {
    saveView(USER, '   ', '/browse?type=Transaction')

    expect(listSavedViews(USER)).toEqual([])
  })

  it('forgets one by name', () => {
    saveView(USER, 'keep', '/browse?type=A')
    saveView(USER, 'drop', '/browse?type=B')

    deleteView(USER, 'drop')

    expect(listSavedViews(USER).map((view) => view.name)).toEqual(['keep'])
  })

  it('keeps one user out of another on a shared machine', () => {
    // localStorage is per-BROWSER. Without keying by username a second
    // person on the same machine inherits the first's saved views --
    // which here would be a list of what their colleague investigates.
    saveView(USER, 'mine', '/browse?type=A')

    expect(listSavedViews('bob')).toEqual([])
  })

  it('skips an entry of an older shape rather than rendering it', () => {
    // THE CONTROL ON TRUST. localStorage is editable by hand and
    // survives across versions of this code.
    // Written through writePreference rather than to a hand-built
    // key: the storage format is that module's business, and a test
    // duplicating it tests its own guess. A first version did, used
    // `savedViews:alice`, and failed against the real
    // `elysium.pref.savedViews.alice`.
    writePreference('savedViews', USER, [{ name: 'fine', url: '/browse', saved_at: 'x' }, { legacy: true }, null])

    expect(listSavedViews(USER).map((view) => view.name)).toEqual(['fine'])
  })

  it('survives storage holding something that is not a list', () => {
    writePreference('savedViews', USER, { not: 'a list' })

    expect(listSavedViews(USER)).toEqual([])
  })
})
