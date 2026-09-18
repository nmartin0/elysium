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

import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getLinkCounts } from '@elysium/shell-api/api'
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

function renderPanel(schema: VisibleSchema | null = SCHEMA) {
  return render(
    <MemoryRouter>
      <ExploreRelated objectType="Customer" objectId="cust_001" visibleSchema={schema} onSessionExpired={vi.fn()} />
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
