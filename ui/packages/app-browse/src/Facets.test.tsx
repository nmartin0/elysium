/**
 * A facet count that is short says so.
 *
 * WHY THIS FILE EXISTS NOW AND NOT WHEN Facets DID. The component
 * shipped with its behaviour covered through `ObjectSearchPanel.test
 * .tsx`, which renders the whole panel -- fine for "do facets appear",
 * useless for this: the panel's own search and a facet's aggregate are
 * SEPARATE requests over DIFFERENT condition sets, and the case worth
 * testing is the one where they disagree.
 *
 * THE CASE WORTH TESTING. `conditionsExcluding` deliberately drops
 * this field's own filter, so a facet aggregates a BROADER set than
 * the table beside it. It can therefore hit the server's scan ceiling
 * on a page where the table did not -- a complete-looking table with
 * silently short counts next to it, which is the shape nobody would
 * catch by looking.
 *
 * "AT LEAST", NEVER "THERE ARE MORE". Past the ceiling the rows might
 * all have been outside this caller's compartment anyway, so the only
 * honest claim is about what was read. The same wording rule the
 * search's own notice follows.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const aggregateObjects = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, aggregateObjects: (...args: unknown[]) => aggregateObjects(...args) }
})

const { default: Facets } = await import('./Facets')

const noop = () => {}

/** Enough distinct values to pass the identifier-ratio test, which
 *  suppresses a facet whose values approach the object count. Four
 *  regions over sixty objects is a facet; four over four is the result
 *  list again. */
const SPREAD = { 'us-west': 30, 'us-east': 18, eu: 9, apac: 3 }

function renderFacet() {
  return render(<Facets objectType="Customer" field="region" label="Region" filters={[]} onFilter={noop} />)
}

beforeEach(() => {
  vi.clearAllMocks()
  aggregateObjects.mockResolvedValue({ results: SPREAD, scan_truncated: false })
})

describe('a facet whose distribution was cut off', () => {
  it('says the counts are floors', async () => {
    aggregateObjects.mockResolvedValue({ results: SPREAD, scan_truncated: true })

    renderFacet()

    expect(await screen.findByText(/At least/)).toBeInTheDocument()
    expect(screen.getByText(/10,000 rows/)).toBeInTheDocument()
  })

  it('still shows the values, so the set can be narrowed below the ceiling', async () => {
    // SUPPRESSING A TRUNCATED FACET WOULD REMOVE THE ONE CONTROL that
    // fixes the truncation. The person needs to click `us-west` to get
    // under the limit; hiding the pills because the counts are
    // imperfect takes that away and leaves them with a bare search
    // box.
    aggregateObjects.mockResolvedValue({ results: SPREAD, scan_truncated: true })

    renderFacet()

    expect(await screen.findByText('us-west')).toBeInTheDocument()
    expect(screen.getByText('30')).toBeInTheDocument()
  })

  it('does not claim there is more for this caller to see', async () => {
    // THE WORDING RULE, asserted rather than trusted to a comment.
    // Beyond the ceiling the rows might all have been in another
    // compartment, so "we stopped counting" is true and "there are
    // more" is a guess -- and the second is the one a person would
    // act on.
    aggregateObjects.mockResolvedValue({ results: SPREAD, scan_truncated: true })

    renderFacet()
    await screen.findByText(/At least/)

    expect(screen.queryByText(/there (are|is) more/i)).not.toBeInTheDocument()
  })
})

describe('an ordinary facet', () => {
  it('says nothing about floors', async () => {
    // THE CONTROL. A notice rendered unconditionally would pass every
    // test above and fail this one, which is the only reason any of
    // them is worth having.
    renderFacet()
    await screen.findByText('us-west')

    expect(screen.queryByText(/At least/)).not.toBeInTheDocument()
    expect(screen.queryByText(/10,000 rows/)).not.toBeInTheDocument()
  })

  it('reports unavailable counts without taking the pane with it', async () => {
    // A FACET IS AN AID, NOT THE SEARCH. The filter bar below still
    // works, so a failed distribution is a line rather than an error
    // state -- and it is NOT the truncation message, which would tell
    // a reader the counts are nearly right when there are none.
    aggregateObjects.mockRejectedValue(new Error('the silo is unreachable'))

    renderFacet()

    expect(await screen.findByText('Counts unavailable.')).toBeInTheDocument()
    expect(screen.queryByText(/At least/)).not.toBeInTheDocument()
  })

  it('suppresses a field whose values identify objects rather than group them', async () => {
    // Four names among four customers is the result list again. Both
    // this and the single-value case have few buckets, which is why a
    // ceiling alone let NAME and EMAIL through and a rendered pane
    // showed them with every count at 1.
    aggregateObjects.mockResolvedValue({ results: { Ada: 1, Bram: 1, Chidi: 1 }, scan_truncated: false })

    renderFacet()
    await waitFor(() => expect(aggregateObjects).toHaveBeenCalledTimes(1))

    expect(screen.queryByText('Region')).not.toBeInTheDocument()
  })
})

describe('a facet counts the SEARCHED set', () => {
  it('sends the search box text', async () => {
    // A facet counting "us-west · 404" under a search that matched 81
    // is counting a different set from the one it would narrow.
    render(<Facets objectType="Customer" field="region" label="Region" filters={[]} onFilter={noop} queryText="ada" />)

    await waitFor(() =>
      expect(aggregateObjects).toHaveBeenCalledWith('Customer', expect.objectContaining({ q: 'ada' })),
    )
  })
})
