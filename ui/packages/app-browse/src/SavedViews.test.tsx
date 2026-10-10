/**
 * SavedViews, now that they live on the server.
 *
 * THESE TESTS EXERCISE THE TWO THINGS ONLY THE COMPONENT DECIDES:
 * that saving captures the CURRENT search as a query, and that
 * opening one navigates back to it.
 *
 * THE SPLIT IS THE PART WORTH PINNING. `type`, `q` and `filters` go
 * to the server as a QUERY a condition can evaluate; `sort` and
 * `view` go as PRESENTATION, kept so restoring a view does not lose
 * somebody's sort order but out of the way of anything counting rows.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getSavedViews: vi.fn(),
    createTrigger: vi.fn(),
    saveSavedView: vi.fn(),
    deleteSavedView: vi.fn(),
  }
})

import { createTrigger, deleteSavedView, getSavedViews, saveSavedView } from '@elysium/shell-api/api'
import SavedViews from './SavedViews'

const mockedList = vi.mocked(getSavedViews)
const mockedSave = vi.mocked(saveSavedView)
const mockedDelete = vi.mocked(deleteSavedView)
const mockedWatch = vi.mocked(createTrigger)

function aView(overrides = {}) {
  return {
    view_id: 'v1',
    name: 'High value',
    object_type: 'Transaction',
    query_text: '',
    conditions: [],
    presentation: {},
    created_at: '2026-01-01T00:00:00+00:00',
    ...overrides,
  }
}

function Where() {
  const location = useLocation()
  return <span data-testid="where">{`${location.pathname}${location.search}`}</span>
}

/** What the router is pointing at now, via the Where probe above. */
function currentUrl(): string {
  return screen.getByTestId('where').textContent ?? ''
}

function renderAt(url: string) {
  return render(
    <MemoryRouter initialEntries={[url]}>
      <Where />
      <Routes>
        <Route path="/browse" element={<SavedViews username="alice" />} />
      </Routes>
    </MemoryRouter>,
  )
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue([])
  mockedSave.mockResolvedValue('v-new')
  mockedWatch.mockResolvedValue('t-new')
})

describe('saving the current search', () => {
  it('sends what matches as a query', async () => {
    renderAt('/browse?type=Transaction&q=refund')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), {
      target: { value: 'Refunds' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockedSave).toHaveBeenCalledWith(
        expect.objectContaining({
          name: 'Refunds',
          object_type: 'Transaction',
          query_text: 'refund',
        }),
      ),
    )
  })

  it('sends sort and view separately, as presentation', async () => {
    /** KEPT, BUT OUT OF THE QUERY. An earlier design dropped these --
     *  right about what a CONDITION needs, wrong about what a SAVED
     *  VIEW is. Somebody restoring one would have lost their sort. */
    renderAt('/browse?type=Transaction&sort=amount&view=chart')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), {
      target: { value: 'By amount' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockedSave).toHaveBeenCalledWith(
        expect.objectContaining({
          presentation: { sort: 'amount', view: 'chart' },
        }),
      ),
    )
  })

  it('refuses to save a search with no object type', async () => {
    // A VIEW WITH NO TYPE matches nothing and the server refuses it.
    // Disabling here says so before the round trip.
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), {
      target: { value: 'Nothing' },
    })

    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })
})

describe('opening a saved view', () => {
  it('navigates back to what it matched', async () => {
    mockedList.mockResolvedValue([aView({ query_text: 'refund', presentation: { sort: 'amount' } })])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    fireEvent.click(await screen.findByText('High value'))

    await waitFor(() => {
      const where = screen.getByTestId('where').textContent ?? ''
      expect(where).toContain('type=Transaction')
      expect(where).toContain('q=refund')
      expect(where).toContain('sort=amount')
    })
  })
})

describe('forgetting one', () => {
  it('deletes it without navigating there first', async () => {
    mockedList.mockResolvedValue([aView()])
    mockedDelete.mockResolvedValue(undefined)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    fireEvent.click(await screen.findByRole('button', { name: /forget high value/i }))

    await waitFor(() => expect(mockedDelete).toHaveBeenCalledWith('v1'))
    expect(screen.getByTestId('where').textContent).toBe('/browse')
  })
})

describe('when the server cannot be reached', () => {
  it('still offers to save', async () => {
    /** A POPOVER THAT CANNOT LIST is still one that can save. An
     *  error banner over a search that is working would be worse. */
    mockedList.mockRejectedValue(new Error('unreachable'))
    renderAt('/browse?type=Transaction')

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    expect(screen.getByPlaceholderText(/name this view/i)).toBeInTheDocument()
  })
})

describe('watching a saved view', () => {
  it('asks what to watch for, then creates it', async () => {
    /** A DIALOG RATHER THAN ANOTHER MENU LEVEL. A threshold needs a
     *  number and a choice, and a submenu asking for both is a form
     *  pretending not to be one. */
    mockedList.mockResolvedValue([aView()])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedWatch).toHaveBeenCalledWith(expect.objectContaining({ name: 'High value', view_id: 'v1' })),
    )
  })

  it('sends exactly one threshold', async () => {
    /** THE SERVER REFUSES TWO -- they would need an answer about
     *  which wins, and two triggers say it plainly instead. */
    mockedList.mockResolvedValue([aView()])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))
    fireEvent.click(await screen.findByRole('button', { name: 'Watch' }))

    await waitFor(() => expect(mockedWatch).toHaveBeenCalled())
    // NON-NULL ASSERTED after the waitFor above proves the call
    // happened -- TypeScript cannot see that the assertion ran.
    const body = mockedWatch.mock.calls[0]![0]
    const set = [body.above, body.gained, body.fell].filter((v) => v !== null)

    expect(set).toHaveLength(1)
  })

  it('watches what was chosen, not always the default', async () => {
    mockedList.mockResolvedValue([aView()])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))
    fireEvent.change(await screen.findByLabelText('When to notify'), {
      target: { value: 'gained' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Watch' }))

    await waitFor(() =>
      expect(mockedWatch).toHaveBeenCalledWith(expect.objectContaining({ above: null, gained: expect.any(Number) })),
    )
  })
})

describe('opening the watch dialog a second time', () => {
  /**
   * WHAT THE BATCH RESET IN WatchDialog WAS FOR. The dialog stays
   * mounted with isOpen toggling, so without something to clear it,
   * everything typed for one view is still there when the next is
   * opened -- and the person is looking at a form that describes a
   * different saved view.
   *
   * Tested HERE rather than in WatchDialog's own file because the
   * replacement is a key at this call site: a fresh instance per
   * opening, which is React's own answer for "reset all state when the
   * identity changes".
   */
  it('starts a different view with an empty threshold', async () => {
    mockedList.mockResolvedValue([aView(), aView({ view_id: 'v2', name: 'Refunds' })])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))
    fireEvent.change(await screen.findByLabelText('How many'), { target: { value: '99' } })
    fireEvent.click(screen.getByRole('button', { name: /close/i }))

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByRole('button', { name: /watch refunds/i }))

    expect(((await screen.findByLabelText('How many')) as HTMLInputElement).value).toBe('10')
  })

  it('starts the SAME view fresh when reopened', async () => {
    // Reopening the same view must reset too -- a key on the view id
    // alone would not, because the id has not changed.
    mockedList.mockResolvedValue([aView()])
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))
    fireEvent.change(await screen.findByLabelText('How many'), { target: { value: '99' } })
    fireEvent.click(screen.getByRole('button', { name: /close/i }))

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByRole('button', { name: /watch high value/i }))

    expect(((await screen.findByLabelText('How many')) as HTMLInputElement).value).toBe('10')
  })
})

describe('a view whose filters are no longer all authorised', () => {
  /**
   * The server re-authorises a saved view at read time, every time, and
   * names the conditions it had to disable. Its own reason for naming
   * them rather than dropping them quietly: "the user sees more rows
   * than the search promised and concludes their data changed".
   *
   * The client did not declare the field, so it arrived and was
   * discarded before any screen could use it. The careful half was
   * done on the server and thrown away here.
   */

  it('marks the view in the list, before it is opened', async () => {
    mockedList.mockResolvedValue([aView({ disabled_conditions: ['region'] })])
    renderAt('/browse')

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    expect(await screen.findByText(/1 filter off/)).toBeTruthy()
  })

  it('counts more than one', async () => {
    mockedList.mockResolvedValue([aView({ disabled_conditions: ['region', 'email'] })])
    renderAt('/browse')

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    expect(await screen.findByText(/2 filters off/)).toBeTruthy()
  })

  it('says nothing when every filter still runs', async () => {
    /** A badge on every view would be noise, and noise is how a real
     *  warning gets ignored. */
    mockedList.mockResolvedValue([aView({ disabled_conditions: [] })])
    renderAt('/browse')

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    await screen.findByText('High value')
    expect(screen.queryByText(/filter/)).toBeNull()
  })

  it('says nothing when the server sends no such field', async () => {
    /** An older server, or a response that predates the field. Absent
     *  must mean "nothing disabled", not "unknown" rendered as a
     *  warning. */
    mockedList.mockResolvedValue([aView()])
    renderAt('/browse')

    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))

    await screen.findByText('High value')
    expect(screen.queryByText(/filter/)).toBeNull()
  })
})

describe('how you got here, which a save used to drop', () => {
  /**
   * DEV_UI.md 11.2 names the traversal chain as the third part of what
   * a set IS -- "object type + conditions + the traversal chain that
   * produced it". The first two were saved and this was not, so "Ada
   * Okafor's transactions" came back as transactions filtered by
   * customer_id: the same ROWS, and a different thing to read.
   */
  const TRAIL = { type: 'Customer', id: 'cust_001', field: 'customer_id' }
  const FILTER = [{ field: 'customer_id', values: ['cust_001'], mode: 'keep' }]

  const arrivedByLink =
    `/browse?type=Transaction&filters=${encodeURIComponent(JSON.stringify(FILTER))}` +
    `&from=${encodeURIComponent(JSON.stringify(TRAIL))}`

  async function saveAs(name: string, url: string) {
    renderAt(url)
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), { target: { value: name } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
  }

  it('sends the trail with the search it describes', async () => {
    await saveAs("Ada's transactions", arrivedByLink)

    await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({ origin: TRAIL })))
  })

  it('sends nothing for a search somebody typed', async () => {
    // Most searches are typed, and an origin invented for one would
    // put a sentence on screen that no link produced.
    await saveAs('Refunds', '/browse?type=Transaction&q=refund')

    await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({ origin: {} })))
  })

  it('treats a malformed trail as none rather than failing the save', async () => {
    // A view that refused to save because one URL key was corrupt
    // would lose the whole search to protect a breadcrumb.
    await saveAs('Odd', '/browse?type=Transaction&from=not-json')

    await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({ origin: {} })))
  })

  it('refuses a trail that is not an object', async () => {
    await saveAs('Odd', `/browse?type=Transaction&from=${encodeURIComponent('[1,2]')}`)

    await waitFor(() => expect(mockedSave).toHaveBeenCalledWith(expect.objectContaining({ origin: {} })))
  })

  it('puts the trail back in the URL when the view is opened', async () => {
    mockedList.mockResolvedValue([aView({ name: "Ada's transactions", conditions: FILTER, origin: TRAIL })] as never)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByText("Ada's transactions"))

    await waitFor(() => expect(currentUrl()).toContain('from='))
    expect(decodeURIComponent(currentUrl())).toContain('"id":"cust_001"')
  })

  /**
   * THE TRAIL CANNOT OUTLIVE ITS FILTER, and nothing in this component
   * enforces that. The server returns the RE-AUTHORISED conditions, so
   * a caller who may no longer run the link filter gets a view whose
   * `conditions` no longer name it -- and `activeTrail` renders
   * nothing without a filter naming that exact id.
   */
  it('still carries the trail when the filter it describes was disabled', async () => {
    mockedList.mockResolvedValue([
      aView({
        name: "Ada's transactions",
        conditions: [],
        disabled_conditions: ['customer_id'],
        origin: TRAIL,
      }),
    ] as never)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByText("Ada's transactions"))

    // The URL carries it; the panel will not show it, because
    // activeTrail has no matching filter to agree with.
    await waitFor(() => expect(currentUrl()).toContain('from='))
    expect(currentUrl()).not.toContain('filters=')
  })

  it('omits the key entirely for a view with no trail', async () => {
    mockedList.mockResolvedValue([aView({ name: 'Refunds', query_text: 'refund', origin: {} })] as never)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByText('Refunds'))

    await waitFor(() => expect(currentUrl()).toContain('q=refund'))
    expect(currentUrl()).not.toContain('from=')
  })
})

describe('the filter vocabulary, which a save used to get wrong', () => {
  /**
   * THE BUG. The URL's `filters` key holds ChartFilters --
   * `{field, values, mode}` -- and the API's conditions are
   * `{field, operator, value}`. The save path wrote the URL's shape
   * straight through, so `parse_filters` threw on every saved view
   * that had a filter, and the route's FilterError branch answered
   * with runnable=[] and disabled=[].
   *
   * The view therefore came back matching EVERY object of its type,
   * with nothing on screen saying a filter had been lost -- which is
   * exactly what `disabled_conditions` was built to prevent.
   *
   * FOUND IN A BROWSER, not here: saving a view reached by following
   * a link and reopening it produced no filter and no trail.
   */
  const CHART_FILTER = [{ field: 'customer_id', values: ['cust_001'], mode: 'keep' }]

  it('saves a filter in the API vocabulary, not the URL one', async () => {
    renderAt(`/browse?type=Transaction&filters=${encodeURIComponent(JSON.stringify(CHART_FILTER))}`)
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), { target: { value: 'Ada' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockedSave).toHaveBeenCalledWith(
        expect.objectContaining({
          conditions: [{ field: 'customer_id', operator: 'in', value: ['cust_001'] }],
        }),
      ),
    )
  })

  it('saves an exclusion as not_in', async () => {
    const excluded = [{ field: 'category', values: ['refund'], mode: 'exclude' }]
    renderAt(`/browse?type=Transaction&filters=${encodeURIComponent(JSON.stringify(excluded))}`)
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.change(screen.getByPlaceholderText(/name this view/i), { target: { value: 'No refunds' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(mockedSave).toHaveBeenCalledWith(
        expect.objectContaining({
          conditions: [{ field: 'category', operator: 'not_in', value: ['refund'] }],
        }),
      ),
    )
  })

  it('puts the filter back in the URL vocabulary when the view is opened', async () => {
    mockedList.mockResolvedValue([
      aView({
        name: 'Ada',
        conditions: [{ field: 'customer_id', operator: 'in', value: ['cust_001'] }],
      }),
    ] as never)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByText('Ada'))

    await waitFor(() => expect(currentUrl()).toContain('filters='))
    const url = decodeURIComponent(currentUrl())
    expect(url).toContain('"mode":"keep"')
    expect(url).toContain('"values":["cust_001"]')
    expect(url).not.toContain('operator')
  })

  /**
   * A condition the chart vocabulary cannot express -- `range`, which
   * the API has and a ChartFilter does not. Inventing one would put a
   * filter on screen that narrows differently from the one saved.
   */
  it('drops a condition it cannot express rather than inventing one', async () => {
    mockedList.mockResolvedValue([
      aView({
        name: 'Big ones',
        conditions: [{ field: 'amount', operator: 'range', value: { min: 100 } }],
      }),
    ] as never)
    renderAt('/browse')
    fireEvent.click(await screen.findByRole('button', { name: /saved views/i }))
    fireEvent.click(await screen.findByText('Big ones'))

    await waitFor(() => expect(currentUrl()).toContain('type=Transaction'))
    expect(currentUrl()).not.toContain('filters=')
  })
})
