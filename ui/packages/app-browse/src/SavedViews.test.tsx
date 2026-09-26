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
