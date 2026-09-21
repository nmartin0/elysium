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
    saveSavedView: vi.fn(),
    deleteSavedView: vi.fn(),
  }
})

import { deleteSavedView, getSavedViews, saveSavedView } from '@elysium/shell-api/api'
import SavedViews from './SavedViews'

const mockedList = vi.mocked(getSavedViews)
const mockedSave = vi.mocked(saveSavedView)
const mockedDelete = vi.mocked(deleteSavedView)

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
