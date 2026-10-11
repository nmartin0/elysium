import { describe, it, expect, vi, beforeEach } from 'vitest'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'

const compareSets = vi.fn()
const combineSets = vi.fn()
const getSavedViews = vi.fn()
const getFrozenSets = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    compareSets: (...args: unknown[]) => compareSets(...args),
    combineSets: (...args: unknown[]) => combineSets(...args),
    getSavedViews: () => getSavedViews(),
    getFrozenSets: () => getFrozenSets(),
  }
})

const { default: CompareSets } = await import('./CompareSets')

function Where() {
  const location = useLocation()
  return <output data-testid="where">{`${location.pathname}${location.search}`}</output>
}

const VIEW = {
  view_id: 'v1',
  name: 'Escalations',
  object_type: 'Customer',
  query_text: '',
  conditions: [],
  presentation: {},
  origin: {},
}
const SET = {
  set_id: 'f1',
  name: 'Q3 picks',
  object_type: 'Customer',
  size: 4,
  frozen_at: '2026-10-11T10:00:00+00:00',
  origin: {},
}
const COUNTS = { left_only: 3, both: 2, right_only: 0, scan_truncated: false }

function popover(props: Partial<Parameters<typeof CompareSets>[0]> = {}) {
  render(
    <MemoryRouter initialEntries={['/browse?type=Customer']}>
      <Routes>
        <Route
          path="*"
          element={
            <>
              <CompareSets
                objectType="Customer"
                queryText="ada"
                conditions={[{ field: 'region', operator: 'in', value: ['us-west'] }]}
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
  fireEvent.click(screen.getByRole('button', { name: /compare/i }))
}

async function choose(label: RegExp) {
  const select = await screen.findByLabelText(/set to compare with/i)
  await waitFor(() => expect(screen.getByRole('option', { name: label })).toBeInTheDocument())
  const option = screen.getByRole('option', { name: label }) as HTMLOptionElement
  // INSIDE act, AWAITED: choosing starts the comparison, and a mocked
  // answer resolves before the next query would begin watching for it.
  await act(async () => {
    fireEvent.change(select, { target: { value: option.value } })
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  getSavedViews.mockResolvedValue([VIEW, { ...VIEW, view_id: 'v2', name: 'Payments', object_type: 'Transaction' }])
  getFrozenSets.mockResolvedValue([SET, { ...SET, set_id: 'here', name: 'On screen' }])
  compareSets.mockResolvedValue(COUNTS)
  combineSets.mockResolvedValue({ ...SET, set_id: 'kept' })
})

describe('choosing what to compare with', () => {
  it('offers saved views and frozen sets of THIS type only', async () => {
    // Ids are unique within a type; a Transaction view compared with
    // Customers would match ids that merely collide.
    popover()

    await screen.findByRole('option', { name: /Escalations/ })
    expect(screen.getByRole('option', { name: /Q3 picks/ })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: /Payments/ })).not.toBeInTheDocument()
  })

  it('does not offer the frozen set already on screen', async () => {
    popover({ activeSetId: 'here' })

    await screen.findByRole('option', { name: /Q3 picks/ })
    expect(screen.queryByRole('option', { name: /On screen/ })).not.toBeInTheDocument()
  })
})

describe('comparing', () => {
  it('sends the set on screen as it is, and the chosen one by reference', async () => {
    popover({ activeSetId: 'here' })
    await choose(/Escalations/)

    await waitFor(() =>
      expect(compareSets).toHaveBeenCalledWith(
        'Customer',
        { q: 'ada', conditions: [{ field: 'region', operator: 'in', value: ['us-west'] }], frozen_set: 'here' },
        { saved_view: 'v1' },
      ),
    )
    await screen.findByRole('row', { name: /In both/ })
  })

  it('sends nothing it does not have', async () => {
    // THE CONTROL for the test above: no text, no filters, no frozen set
    // is every object of the type, sent as an empty reference.
    popover({ queryText: '', conditions: [] })
    await choose(/Q3 picks/)

    await waitFor(() => expect(compareSets).toHaveBeenCalledWith('Customer', {}, { frozen_set: 'f1' }))
    await screen.findByRole('row', { name: /In both/ })
  })

  it('shows the three regions and their union', async () => {
    popover()
    await choose(/Escalations/)

    const only = await screen.findByRole('row', { name: /Only in this set/ })
    expect(only).toHaveTextContent('3')
    expect(screen.getByRole('row', { name: /In both/ })).toHaveTextContent('2')
    expect(screen.getByRole('row', { name: /Only in Escalations/ })).toHaveTextContent('0')
    expect(screen.getByRole('row', { name: /In either/ })).toHaveTextContent('5')
  })

  it('will not keep an empty region', async () => {
    popover()
    await choose(/Escalations/)

    expect(await screen.findByRole('button', { name: /keep only in escalations/i })).toBeDisabled()
    expect(screen.getByRole('button', { name: /keep in both/i })).toBeEnabled()
  })

  it('says so, and keeps nothing, when a side was too large to read', async () => {
    compareSets.mockResolvedValue({ ...COUNTS, scan_truncated: true })
    popover()
    await choose(/Escalations/)

    expect(await screen.findByText(/larger than a search reads/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /keep in both/i })).toBeDisabled()
  })

  it("shows the server's words when it refuses", async () => {
    const { ApiError } = await import('@elysium/shell-api/api')
    compareSets.mockRejectedValue(new ApiError(400, '“Escalations” filters on fields you can no longer read'))
    popover()
    await choose(/Escalations/)

    expect(await screen.findByText(/can no longer read/)).toBeInTheDocument()
  })
})

describe('keeping a region', () => {
  it('keeps it as a frozen set and opens it', async () => {
    popover()
    await choose(/Escalations/)

    fireEvent.click(await screen.findByRole('button', { name: /keep in both/i }))

    await waitFor(() =>
      expect(combineSets).toHaveBeenCalledWith(
        'Customer',
        expect.objectContaining({ q: 'ada' }),
        { saved_view: 'v1' },
        'both',
        'This set and Escalations',
      ),
    )
    await waitFor(() => expect(screen.getByTestId('where').textContent).toBe('/browse?type=Customer&frozen=kept'))
  })
})
