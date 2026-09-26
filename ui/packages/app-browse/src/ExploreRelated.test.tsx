/**
 * Where each link leads, and how far.
 *
 * COUNTS BEFORE EXPANSION is the whole design: a person deciding
 * whether to follow a link needs to know it leads to four things or
 * four thousand before they commit.
 *
 * ONE HOP AT A TIME, deliberately. No canvas, no layout, no automatic
 * multi-hop expansion -- those are the "full Vertex" item, and
 * reaching them by accident is how a read-only explorer becomes
 * something nobody can reason about on a real ontology.
 */

import { act, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, getLinkCounts } from '@elysium/shell-api/api'
import type { VisibleSchema } from '@elysium/shell-api/types'

import ExploreRelated from './ExploreRelated'

vi.mock('@elysium/shell-api/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@elysium/shell-api/api')>()),
  getLinkCounts: vi.fn(),
}))

const mockedGetLinkCounts = vi.mocked(getLinkCounts)

// Transaction.customer_id points back at Customer -- which is what a
// filter on the target actually needs.
const SCHEMA: VisibleSchema = {
  Customer: { fields: { transactions: { type: 'link', target: 'Transaction' } } },
  Transaction: { fields: { customer_id: { type: 'link', target: 'Customer' } } },
}

function renderPanel(schema: VisibleSchema | null = SCHEMA, onSessionExpired: () => void = vi.fn()) {
  return render(
    <MemoryRouter>
      <ExploreRelated
        objectType="Customer"
        objectId="cust_001"
        visibleSchema={schema}
        onSessionExpired={onSessionExpired}
      />
    </MemoryRouter>,
  )
}

beforeEach(() => vi.clearAllMocks())

describe('ExploreRelated', () => {
  it('shows how many objects a link leads to', async () => {
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 47, cardinality: 'many' },
    })
    renderPanel()

    expect(await screen.findByText('47 Transaction')).toBeInTheDocument()
  })

  it('carries an origin that brings up the trail in Browse', async () => {
    /** WRITER AND READER, TESTED AGAINST EACH OTHER. This builds the
     *  link; linkTrail.ts reads it. If either drifted -- a renamed key,
     *  a changed filter shape -- the trail would silently never show,
     *  and each side's own tests would still pass. So the link's own
     *  URL is fed to the reader and must produce a trail. */
    const { activeTrail } = await import('./linkTrail')
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 2, cardinality: 'many' },
    })
    renderPanel()

    const link = await screen.findByRole('link', { name: /2 Transaction/ })
    const params = new URLSearchParams(link.getAttribute('href')!.split('?')[1])

    const trail = activeTrail(JSON.parse(params.get('from')!), JSON.parse(params.get('filters')!))

    expect(trail).toEqual({ type: 'Customer', id: 'cust_001', field: 'customer_id' })
  })

  it('links through the REVERSE field, not the forward one', async () => {
    /** THE BUG THIS TEST EXISTS FOR.
     *
     * To see cust_001's transactions you filter Transaction on
     * `customer_id`. Filtering it on `transactions` is refused by the
     * backend as invalid search criteria -- verified directly -- so a
     * link built from the forward field name would be a dead end that
     * looked live.
     */
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 2, cardinality: 'many' },
    })
    renderPanel()

    const link = await screen.findByRole('link', { name: /2 Transaction/ })
    expect(link).toHaveAttribute('href', expect.stringContaining('customer_id'))
    expect(link.getAttribute('href')).not.toContain('%22transactions%22')
  })

  it('does not offer navigation when nothing is there', async () => {
    // A clickable row leading to an empty result is a promise the data
    // does not keep.
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 0, cardinality: 'many' },
    })
    renderPanel()

    expect(await screen.findByText('None')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('shows the count without a link when no reverse field exists', async () => {
    // An honest count beats a link that goes nowhere. Without a
    // reverse link there is no filter that expresses the question.
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 5, cardinality: 'many' },
    })
    renderPanel({
      Customer: { fields: { transactions: { type: 'link', target: 'Transaction' } } },
      Transaction: { fields: {} },
    })

    expect(await screen.findByText('5 Transaction')).toBeInTheDocument()
    expect(screen.queryByRole('link')).toBeNull()
  })

  it('says so plainly when an object links to nothing', async () => {
    // An ordinary state, not an error -- and better than a blank area
    // that reads as a failed render.
    mockedGetLinkCounts.mockResolvedValue({})
    renderPanel()

    expect(await screen.findByText('Nothing links from this record.')).toBeInTheDocument()
  })

  it('surfaces a failure rather than showing nothing', async () => {
    mockedGetLinkCounts.mockRejectedValue(new Error('the silo is unreachable'))
    renderPanel()

    expect(await screen.findByText(/the silo is unreachable/)).toBeInTheDocument()
  })

  it('announces while it is counting', async () => {
    // Counting means a query per link. On this hardware that is worth
    // saying out loud rather than leaving a blank space.
    mockedGetLinkCounts.mockReturnValue(new Promise(() => {}))
    renderPanel()

    await waitFor(() => expect(screen.getByRole('status')).toHaveTextContent('Counting related records…'))
  })
})

describe('ExploreRelated -- an expired session', () => {
  /**
   * FOUND WHILE FIXING F-31, and worse than the item itself.
   *
   * This panel LOOKED handled: its catch tested
   * `getErrorMessage(caught).includes('401')` before calling
   * onSessionExpired. But api/auth_dependency.py answers an expired
   * session with `detail: "Invalid or expired session"` -- a sentence
   * containing no digits at all -- and api.ts puts that detail in the
   * message. So the branch could never run for the case it was
   * written for, and the code READ as correct while doing nothing.
   *
   * The string test was also wrong in the other direction: any
   * message that happened to contain "401" -- a note, an object id, a
   * count -- would have logged the person out.
   */
  it('sends the person back to login when the session has expired', async () => {
    mockedGetLinkCounts.mockRejectedValue(new ApiError(401, 'Invalid or expired session'))
    const onSessionExpired = vi.fn()

    renderPanel(SCHEMA, onSessionExpired)

    await waitFor(() => expect(onSessionExpired).toHaveBeenCalledTimes(1))
  })

  it('does not log the person out over a message that merely mentions 401', async () => {
    // The string match this replaces would have fired on this.
    mockedGetLinkCounts.mockRejectedValue(new ApiError(500, 'Upstream job 401 failed'))
    const onSessionExpired = vi.fn()

    renderPanel(SCHEMA, onSessionExpired)

    await waitFor(() => expect(screen.getByText(/Upstream job 401 failed/)).toBeInTheDocument())
    expect(onSessionExpired).not.toHaveBeenCalled()
  })
})

describe('ExploreRelated -- the shell re-rendering', () => {
  it('counts links once across parent renders, not once per render', async () => {
    /**
     * The same defect patch 12 fixed in seven panels, in one its guard
     * did not match: onSessionExpired sat BESIDE objectType and
     * objectId in the dependency array rather than alone.
     */
    mockedGetLinkCounts.mockResolvedValue({})
    const { rerender } = renderPanel(SCHEMA, vi.fn())
    await waitFor(() => expect(mockedGetLinkCounts).toHaveBeenCalled())

    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_001" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )
    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_001" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    expect(mockedGetLinkCounts).toHaveBeenCalledTimes(1)
  })

  it('still refetches when the OBJECT changes, which is the point', async () => {
    // The opposite direction: dropping onSessionExpired must not also
    // drop the dependencies that genuinely should refetch.
    mockedGetLinkCounts.mockResolvedValue({})
    const { rerender } = renderPanel(SCHEMA, vi.fn())
    await waitFor(() => expect(mockedGetLinkCounts).toHaveBeenCalledTimes(1))

    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_002" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    await waitFor(() => expect(mockedGetLinkCounts).toHaveBeenCalledTimes(2))
  })
})

describe('ExploreRelated -- moving to another object', () => {
  /**
   * WHAT THE SYNCHRONOUS RESET WAS FOR, and what must survive removing
   * it. Counts belong to a specific object. Showing the previous
   * object's link counts under a new one is a wrong answer presented
   * confidently -- and unlike a missing count, nothing about it looks
   * wrong on screen.
   */
  it('never shows the previous object counts while the next is loading', async () => {
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 7, cardinality: 'many' },
    })
    const { rerender } = renderPanel(SCHEMA, vi.fn())
    expect(await screen.findByText('7 Transaction')).toBeInTheDocument()

    // The next object's count never settles, so what is on screen is
    // what a reader sees for as long as it takes.
    mockedGetLinkCounts.mockReturnValue(new Promise(() => {}))
    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_002" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    expect(screen.queryByText('7 Transaction')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Counting related records…')
  })

  it('clears a previous failure rather than showing it over new counts', async () => {
    // The error is reset too, and for the same reason: a failure for
    // one object is not a failure for the next.
    mockedGetLinkCounts.mockRejectedValue(new Error('the counter fell over'))
    const { rerender } = renderPanel(SCHEMA, vi.fn())
    expect(await screen.findByText(/the counter fell over/)).toBeInTheDocument()

    mockedGetLinkCounts.mockReturnValue(new Promise(() => {}))
    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_002" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    expect(screen.queryByText(/the counter fell over/)).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Counting related records…')
  })

  it('does not reuse counts across two types that share an id', async () => {
    // FOUND BY A CONTROL: dropping the type from the tag passed every
    // other test. Ids are scoped per type -- getLinkCounts takes both
    // -- so matching on id alone would label one type's counts with
    // another's name.
    mockedGetLinkCounts.mockResolvedValue({
      transactions: { target: 'Transaction', count: 7, cardinality: 'many' },
    })
    const { rerender } = renderPanel(SCHEMA, vi.fn())
    expect(await screen.findByText('7 Transaction')).toBeInTheDocument()

    mockedGetLinkCounts.mockReturnValue(new Promise(() => {}))
    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Account" objectId="cust_001" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )

    expect(screen.queryByText('7 Transaction')).not.toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('Counting related records…')
  })

  it('does not let a slow earlier response overwrite a newer one', async () => {
    /**
     * THE STALE GUARD, which tagging does NOT make redundant -- also
     * found by a control, because removing it passed everything else.
     *
     * Tagging stops a stale result being displayed. It does not stop
     * one being STORED: a late response for the previous object would
     * overwrite the newer object's counts, and those newer counts DO
     * match, so they would vanish and the panel would fall back to
     * "counting" forever.
     */
    let settleFirst: ((value: unknown) => void) | undefined
    mockedGetLinkCounts.mockReturnValueOnce(
      new Promise((resolve) => {
        settleFirst = resolve
      }) as never,
    )
    const { rerender } = renderPanel(SCHEMA, vi.fn())

    // Move on before the first ever answers; the second is immediate.
    mockedGetLinkCounts.mockResolvedValue({
      payments: { target: 'Payment', count: 3, cardinality: 'many' },
    })
    rerender(
      <MemoryRouter>
        <ExploreRelated objectType="Customer" objectId="cust_002" visibleSchema={SCHEMA} onSessionExpired={vi.fn()} />
      </MemoryRouter>,
    )
    expect(await screen.findByText('3 Payment')).toBeInTheDocument()

    // Now the first object's answer finally arrives.
    await act(async () => {
      settleFirst?.({ transactions: { target: 'Transaction', count: 7, cardinality: 'many' } })
    })

    expect(screen.getByText('3 Payment')).toBeInTheDocument()
    expect(screen.queryByText('7 Transaction')).not.toBeInTheDocument()
  })
})
