import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const freezeSet = vi.fn()
const getFrozenSets = vi.fn()
const getFrozenSet = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    freezeSet: (...args: unknown[]) => freezeSet(...args),
    getFrozenSets: () => getFrozenSets(),
    getFrozenSet: (...args: unknown[]) => getFrozenSet(...args),
    deleteFrozenSet: vi.fn(),
  }
})

const { default: FrozenSets } = await import('./FrozenSets')
const { default: FrozenNotice } = await import('./FrozenNotice')

/** Where the router ended up, so a test can assert on navigation
 *  rather than on a mocked navigate. */
function Where() {
  const location = useLocation()
  return <output data-testid="where">{`${location.pathname}${location.search}`}</output>
}

const SET = {
  set_id: 'set-1',
  name: 'Escalations',
  object_type: 'Customer',
  size: 3,
  frozen_at: '2026-10-11T10:00:00+00:00',
  published_at: '2026-10-11T09:00:00+00:00',
  publication_retained: true,
  origin: {},
}

function popover(props: Partial<Parameters<typeof FrozenSets>[0]> = {}) {
  render(
    <MemoryRouter initialEntries={['/browse?type=Customer']}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <FrozenSets
                objectType="Customer"
                queryText="ada"
                conditions={[{ field: 'region', operator: 'in', value: ['us-west'] }]}
                selectedIds={[]}
                activeSetId=""
                onSessionExpired={vi.fn()}
                {...props}
              />
              <Where />
            </>
          }
        />
      </Routes>
    </MemoryRouter>,
  )
  fireEvent.click(screen.getByRole('button', { name: /frozen sets/i }))
}

beforeEach(() => {
  vi.clearAllMocks()
  getFrozenSets.mockResolvedValue([])
  freezeSet.mockResolvedValue(SET)
})

describe('freezing', () => {
  it('freezes EVERYTHING MATCHING when nothing is selected', async () => {
    popover()

    fireEvent.change(await screen.findByLabelText(/name for the frozen set/i), { target: { value: 'West' } })
    fireEvent.click(screen.getByRole('button', { name: /freeze everything matching/i }))

    await waitFor(() =>
      expect(freezeSet).toHaveBeenCalledWith({
        name: 'West',
        object_type: 'Customer',
        q: 'ada',
        conditions: [{ field: 'region', operator: 'in', value: ['us-west'] }],
      }),
    )
  })

  it('freezes THE SELECTION when there is one', async () => {
    // "Freeze" alone does not say whether it means the three rows
    // ticked or the 404 matching, so the button says which.
    popover({ selectedIds: ['c1', 'c2'] })

    fireEvent.change(await screen.findByLabelText(/name for the frozen set/i), { target: { value: 'Picked' } })
    fireEvent.click(screen.getByRole('button', { name: /freeze 2 selected/i }))

    await waitFor(() =>
      expect(freezeSet).toHaveBeenCalledWith({ name: 'Picked', object_type: 'Customer', ids: ['c1', 'c2'] }),
    )
  })

  it('freezes WITHIN the frozen set on screen', async () => {
    popover({ activeSetId: 'set-0' })

    fireEvent.change(await screen.findByLabelText(/name for the frozen set/i), { target: { value: 'Inner' } })
    fireEvent.click(screen.getByRole('button', { name: /freeze everything matching/i }))

    await waitFor(() => expect(freezeSet).toHaveBeenCalledWith(expect.objectContaining({ frozen_set: 'set-0' })))
  })

  it('opens the set it just froze', async () => {
    popover()

    fireEvent.change(await screen.findByLabelText(/name for the frozen set/i), { target: { value: 'West' } })
    fireEvent.click(screen.getByRole('button', { name: /freeze everything matching/i }))

    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/browse?type=Customer&frozen=set-1'))
  })

  it("shows the server's words when it refuses", async () => {
    // "404 objects match, and at most 1000 can be frozen at once.
    // Narrow the filter." says what to do; a generic error does not.
    const { ApiError } = await import('@elysium/shell-api/api')
    freezeSet.mockRejectedValue(new ApiError(400, '1500 objects match, and at most 1000 can be frozen at once.'))
    popover()

    fireEvent.change(await screen.findByLabelText(/name for the frozen set/i), { target: { value: 'Too many' } })
    fireEvent.click(screen.getByRole('button', { name: /freeze everything matching/i }))

    expect(await screen.findByText(/at most 1000 can be frozen/)).toBeInTheDocument()
  })
})

describe('the notice on a frozen set', () => {
  function notice(detail: Record<string, unknown>) {
    getFrozenSet.mockResolvedValue({ ...SET, not_shown: 0, ...detail })
    render(
      <MemoryRouter initialEntries={['/browse?type=Customer&frozen=set-1']}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <FrozenNotice setId="set-1" objectType="Customer" onSessionExpired={vi.fn()} />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>,
    )
  }

  it('says when it was frozen and that membership, not values, is fixed', async () => {
    notice({})

    expect(await screen.findByText(/Values shown are current; membership is not/)).toBeInTheDocument()
  })

  it('counts members it cannot show, without saying why', async () => {
    // A deleted member and one outside the reader's compartment look
    // the same, on purpose.
    notice({ not_shown: 1 })

    expect(await screen.findByText(/1 of 3 cannot be shown/)).toBeInTheDocument()
  })

  it('says nothing about that when every member is shown', async () => {
    // THE CONTROL for the test above.
    notice({ not_shown: 0 })

    await screen.findByText(/membership is not/)
    expect(screen.queryByText(/cannot be shown/)).not.toBeInTheDocument()
  })

  it('says when its publication has been forgotten, and only then', async () => {
    notice({ publication_retained: false })

    expect(await screen.findByText(/has since been forgotten/)).toBeInTheDocument()
  })

  it('does not mention it while the publication is kept', async () => {
    notice({ publication_retained: true })

    await screen.findByText(/membership is not/)
    expect(screen.queryByText(/forgotten/)).not.toBeInTheDocument()
  })

  it('returns to its live criteria in ONE navigation', async () => {
    // Three URL setters in a row keep only the last -- the panel
    // records it. This is one URL: the type, the text, the filters,
    // and no frozen set.
    notice({ origin: { q: 'ada', conditions: [{ field: 'region', operator: 'in', value: ['us-west'] }] } })

    fireEvent.click(await screen.findByRole('button', { name: /return to its live criteria/i }))

    const where = new URL(`http://x${screen.getByTestId('where').textContent}`)
    expect(where.searchParams.get('type')).toBe('Customer')
    expect(where.searchParams.get('q')).toBe('ada')
    expect(JSON.parse(where.searchParams.get('filters') ?? '[]')).toEqual([
      { field: 'region', values: ['us-west'], mode: 'keep' },
    ])
    expect(where.searchParams.get('frozen')).toBeNull()
  })

  it('offers no return for a hand-picked selection, which has no criteria', async () => {
    notice({ origin: {} })

    await screen.findByText(/membership is not/)
    expect(screen.queryByRole('button', { name: /return to its live criteria/i })).not.toBeInTheDocument()
  })

  it('offers no return for a part of a comparison, and says what it is', async () => {
    // "Return to its live criteria" on a set with none navigated to the
    // whole type -- a wider set than anything compared.
    notice({ origin: { compare: { region: 'both' } } })

    expect(await screen.findByText(/Kept from a comparison/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /return to its live criteria/i })).not.toBeInTheDocument()
  })

  it('offers no return for a set narrowed inside another', async () => {
    notice({ origin: { within: 'set-0' } })

    await screen.findByText(/membership is not/)
    expect(screen.queryByRole('button', { name: /return to its live criteria/i })).not.toBeInTheDocument()
  })

  it('says so when the set is not available, rather than showing nothing', async () => {
    getFrozenSet.mockRejectedValue(new Error('404'))
    render(
      <MemoryRouter>
        <FrozenNotice setId="nope" objectType="Customer" onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    expect(await screen.findByText(/not available/)).toBeInTheDocument()
  })
})
