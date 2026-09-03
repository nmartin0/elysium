import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

vi.mock('@elysium/shell-api/api', () => {
  class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  }
  return {
    searchObjects: vi.fn(),
    ApiError,
    handleIfSessionExpired: (err: unknown, onSessionExpired: () => void) => {
      if (err instanceof ApiError && err.status === 401) {
        onSessionExpired()
        return true
      }
      return false
    },
  }
})

import { searchObjects, ApiError } from '@elysium/shell-api/api'
import ObjectSearchPanel, { type SearchResult } from './ObjectSearchPanel'
import type { VisibleSchema } from './ObjectDetailPanel'

const mockedSearchObjects = vi.mocked(searchObjects)

const CUSTOMER_SCHEMA: VisibleSchema = {
  Customer: { title_field: 'name', fields: { name: { type: 'data' }, region: { type: 'data' } } },
  Account: { fields: { balance: { type: 'data' } } },
}

// Real timers throughout this file, deliberately -- NOT vi.
// useFakeTimers(). Confirmed directly, via a real debug run, that
// fake timers here produce a genuine, reproducible flake: React's
// own act() wrapping adds microtask hops beyond what even
// vi.advanceTimersByTimeAsync() plus several manual Promise.resolve()
// flushes reliably drained (real "not wrapped in act()" warnings and
// a still-stale DOM even after the extra flushing). Real timers +
// waitFor()'s own real polling is slower per test (the real,
// unshortened 300ms debounce genuinely elapses) but is what actually,
// reliably passes -- correctness over speed, matching this project's
// own established testing discipline elsewhere.
function renderPanel(visibleSchema: VisibleSchema | null, onSessionExpired: () => void = vi.fn()) {
  return render(
    <MemoryRouter>
      <ObjectSearchPanel visibleSchema={visibleSchema} onSessionExpired={onSessionExpired} />
    </MemoryRouter>,
  )
}

function searchResult(results: SearchResult[], totalMatches?: number) {
  return { results, total_matches: totalMatches ?? results.length }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('ObjectSearchPanel -- loading and empty states', () => {
  it('shows "Loading…" while visibleSchema has not arrived yet (null)', () => {
    renderPanel(null)
    expect(screen.getByText('Loading…')).toBeInTheDocument()
  })

  it('shows "Nothing available to search yet." when visibleSchema is empty', () => {
    renderPanel({})
    expect(screen.getByText('Nothing available to search yet.')).toBeInTheDocument()
  })

  it('does not call searchObjects at all when there is nothing to search', async () => {
    renderPanel({})
    await new Promise((resolve) => setTimeout(resolve, 500))
    expect(mockedSearchObjects).not.toHaveBeenCalled()
  })
})

describe('ObjectSearchPanel -- type selection', () => {
  it('renders every real object type as a select option, defaulting to the first', () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)
    expect(screen.getByRole('combobox')).toHaveValue('Customer')
    expect(screen.getByRole('option', { name: 'Customer' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Account' })).toBeInTheDocument()
  })

  it('changing the selected type triggers a new, real search for that type', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)
    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Customer', ''))
    mockedSearchObjects.mockClear()

    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Account' } })

    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Account', ''))
  })
})

describe('ObjectSearchPanel -- debouncing', () => {
  it('does not call searchObjects immediately on keystroke -- only after the debounce delay', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)
    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Customer', ''))
    mockedSearchObjects.mockClear()

    fireEvent.change(screen.getByPlaceholderText('Search Customer…'), { target: { value: 'a' } })
    expect(mockedSearchObjects).not.toHaveBeenCalled()

    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Customer', 'a'))
  })

  it('rapid typing only ever fires ONE real search, for the final, settled value', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)
    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Customer', ''))
    mockedSearchObjects.mockClear()

    const input = screen.getByPlaceholderText('Search Customer…')
    fireEvent.change(input, { target: { value: 'a' } })
    fireEvent.change(input, { target: { value: 'ad' } })
    fireEvent.change(input, { target: { value: 'ada' } })

    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledWith('Customer', 'ada'))
    expect(mockedSearchObjects).toHaveBeenCalledTimes(1)
  })
})

describe('ObjectSearchPanel -- results rendering', () => {
  it('shows real results once the search resolves', async () => {
    mockedSearchObjects.mockResolvedValue(
      searchResult([{ id: 'cust_001', fields: { name: 'Ada Okafor', region: 'us-west' } }]),
    )
    renderPanel(CUSTOMER_SCHEMA)

    // Scoped to the specific title element, not a bare text match --
    // "Ada Okafor" genuinely, deliberately appears TWICE in a real
    // result card (once as the title, once again as the raw "Name"
    // field's own value below it), so an unscoped getByText() would
    // correctly throw "found multiple elements" here, not a bug in
    // the component, just real, expected redundancy this test needs
    // to be specific enough to see past.
    await waitFor(() =>
      expect(screen.getByText('Ada Okafor', { selector: '.object-search__result-title' })).toBeInTheDocument(),
    )
    expect(screen.getByText('us-west')).toBeInTheDocument()
  })

  it('uses title_field as the title, and shows the raw id as a separate subtitle', async () => {
    mockedSearchObjects.mockResolvedValue(
      searchResult([{ id: 'cust_001', fields: { name: 'Ada Okafor', region: 'us-west' } }]),
    )
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() =>
      expect(screen.getByText('Ada Okafor', { selector: '.object-search__result-title' })).toBeInTheDocument(),
    )
    expect(screen.getByText('cust_001')).toBeInTheDocument()
  })

  it('falls back to the raw id as the title (with NO redundant subtitle) when the type has no title_field', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([{ id: 'acct_001', fields: { balance: 500 } }]))
    renderPanel(CUSTOMER_SCHEMA)
    fireEvent.change(screen.getByRole('combobox'), { target: { value: 'Account' } })

    await waitFor(() => expect(screen.getByText('acct_001')).toBeInTheDocument())
    // The id appears exactly once (as the title) -- not a second time
    // as a redundant subtitle, since title === id here.
    expect(screen.getAllByText('acct_001')).toHaveLength(1)
  })

  it('links each result to its real object detail page', async () => {
    mockedSearchObjects.mockResolvedValue(
      searchResult([{ id: 'cust_001', fields: { name: 'Ada Okafor', region: 'us-west' } }]),
    )
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() => expect(screen.getByRole('link')).toHaveAttribute('href', '/objects/Customer/cust_001'))
  })

  it('encodes an id containing a slash in the link, so it cannot split the URL path', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([{ id: 'weird/id', fields: { name: 'Weird', region: 'us' } }]))
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() => expect(screen.getByRole('link')).toHaveAttribute('href', '/objects/Customer/weird%2Fid'))
  })

  it('shows "No results." only once loading has finished and nothing came back', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() => expect(screen.getByText('No results.')).toBeInTheDocument())
  })

  it('shows the "narrow your search" hint when total_matches exceeds the returned results', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([{ id: 'cust_001', fields: { name: 'Ada', region: 'us' } }], 75))
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() => expect(screen.getByText(/Showing 1 of 75 matches/)).toBeInTheDocument())
  })

  it('shows no "narrow your search" hint when every match was returned', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([{ id: 'cust_001', fields: { name: 'Ada', region: 'us' } }]))
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() =>
      expect(screen.getByText('Ada', { selector: '.object-search__result-title' })).toBeInTheDocument(),
    )
    expect(screen.queryByText(/narrow your search/)).not.toBeInTheDocument()
  })
})

describe('ObjectSearchPanel -- the "Searching…" loading indicator', () => {
  it('shows "Searching…" immediately once a search is pending -- even before the debounce delay elapses', () => {
    // setLoading(true) is synchronous, at the TOP of the effect --
    // fires the moment selectedType is known, not gated behind the
    // debounced setTimeout below it. Confirmed directly against the
    // real component code, not assumed.
    mockedSearchObjects.mockReturnValue(new Promise(() => {}))
    renderPanel(CUSTOMER_SCHEMA)

    expect(screen.getByText('Searching…')).toBeInTheDocument()
  })

  it('clears "Searching…" once the real, debounced request resolves', async () => {
    mockedSearchObjects.mockResolvedValue(searchResult([]))
    renderPanel(CUSTOMER_SCHEMA)
    expect(screen.getByText('Searching…')).toBeInTheDocument()

    await waitFor(() => expect(screen.queryByText('Searching…')).not.toBeInTheDocument())
  })
})

describe('ObjectSearchPanel -- error handling', () => {
  it('shows the error message on a non-401 failure', async () => {
    mockedSearchObjects.mockRejectedValue(new ApiError(500, 'Search backend unavailable'))
    renderPanel(CUSTOMER_SCHEMA)

    await waitFor(() => expect(screen.getByText('Search backend unavailable')).toBeInTheDocument())
  })

  it('calls onSessionExpired and shows no error text on a 401', async () => {
    mockedSearchObjects.mockRejectedValue(new ApiError(401, 'session expired'))
    const onSessionExpired = vi.fn()
    renderPanel(CUSTOMER_SCHEMA, onSessionExpired)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
    expect(screen.queryByText('session expired')).not.toBeInTheDocument()
  })
})

describe('ObjectSearchPanel -- the real race-condition guard', () => {
  it('a SLOWER, earlier request resolving AFTER a faster, later one must never overwrite its already-correct results', async () => {
    // Two real, separate searchObjects() calls -- both debounce
    // periods genuinely elapse, both real requests are in flight at
    // once, each with its own, manually-controlled promise. Resolved
    // deliberately OUT OF ORDER: the second (later) call's promise
    // resolves FIRST, then the first (earlier) call's promise
    // resolves LAST -- exactly the real, well-known race this
    // component's own latestRequestId ref exists to guard against.
    //
    // mockImplementation() + explicit call-count tracking here,
    // deliberately, not mockReturnValueOnce().mockReturnValueOnce()
    // chaining -- confirmed directly (not assumed) that the chained
    // form produced a genuine, reproducible failure in this specific
    // test, while this form does not; a real, if not fully explained,
    // difference in how the two interact with this component's own
    // effect-driven call timing, not a hypothetical concern.
    let resolveFirst: ((value: unknown) => void) | undefined
    let resolveSecond: ((value: unknown) => void) | undefined
    mockedSearchObjects.mockImplementation(() => {
      const callNumber = mockedSearchObjects.mock.calls.length
      return new Promise((resolve) => {
        if (callNumber === 1) resolveFirst = resolve
        else if (callNumber === 2) resolveSecond = resolve
      })
    })

    renderPanel(CUSTOMER_SCHEMA)
    // Call #1 fires on mount (queryText starts as '').
    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledTimes(1))

    // Call #2 fires once the user types and the SECOND debounce
    // period elapses.
    fireEvent.change(screen.getByPlaceholderText('Search Customer…'), { target: { value: 'ada' } })
    await waitFor(() => expect(mockedSearchObjects).toHaveBeenCalledTimes(2))

    // The LATER call resolves FIRST (it was faster).
    resolveSecond!(searchResult([{ id: 'cust_002', fields: { name: 'Correct Result', region: 'us' } }]))
    await waitFor(() =>
      expect(screen.getByText('Correct Result', { selector: '.object-search__result-title' })).toBeInTheDocument(),
    )

    // The EARLIER call finally resolves LAST (it was slower) -- its
    // stale results must be silently discarded, not applied.
    resolveFirst!(searchResult([{ id: 'cust_001', fields: { name: 'Stale Result', region: 'us' } }]))
    // A real, deliberate wait -- there is no "resolved" signal to
    // await for a discarded response (nothing should happen at all).
    await new Promise((resolve) => setTimeout(resolve, 200))

    expect(screen.getByText('Correct Result', { selector: '.object-search__result-title' })).toBeInTheDocument()
    expect(screen.queryByText('Stale Result')).not.toBeInTheDocument()
  })
})
