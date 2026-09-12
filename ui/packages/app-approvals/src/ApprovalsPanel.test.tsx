import { describe, expect, it, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getAwaitingWrites: vi.fn(),
    getWriteDetail: vi.fn(),
    confirmWrite: vi.fn(),
  }
})

import { confirmWrite, getAwaitingWrites, getWriteDetail } from '@elysium/shell-api/api'

import ApprovalsPanel from './ApprovalsPanel'

const mockedList = vi.mocked(getAwaitingWrites)
const mockedDetail = vi.mocked(getWriteDetail)
const mockedConfirm = vi.mocked(confirmWrite)

function write(overrides = {}) {
  return {
    write_id: 'w1',
    action_type_name: 'RecategorizeTransaction',
    description: 'Change which category a transaction is filed under. (New category: travel)',
    proposed_by: 'alice',
    proposed_at: new Date().toISOString(),
    object_count: 1,
    expires_at: new Date(Date.now() + 3600_000).toISOString(),
    awaiting_your_review: true,
    proposed_by_you: false,
    undeclared_fields: [],
    duplicate_count: 0,
    ...overrides,
  }
}

beforeEach(() => {
  vi.clearAllMocks()
  mockedList.mockResolvedValue([])
})

describe('ApprovalsPanel', () => {
  it('says so plainly when nothing is waiting', async () => {
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Nothing waiting')).toBeInTheDocument()
  })

  it('leads with the description, not the action name', async () => {
    // The description is the sentence a reviewer reads to decide
    // whether to look further. It was a Python repr until recently,
    // which is why this asserts the readable form specifically.
    mockedList.mockResolvedValue([write()])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Change which category/)).toBeInTheDocument()
  })

  it('offers Approve only where the server says this user may', async () => {
    // NOT THE CONTROL -- the confirm route checks again. This is the
    // button not lying about what will happen.
    mockedList.mockResolvedValue([write({ awaiting_your_review: false, proposed_by_you: true })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText(/Change which category/)
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
    expect(screen.getByText('Proposed by you')).toBeInTheDocument()
  })

  it('shows both tags when both are true', async () => {
    // A deployment with no four-eyes rule lets someone approve their
    // own write, and showing one tag would misreport the other.
    mockedList.mockResolvedValue([write({ proposed_by_you: true })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Awaiting your review')).toBeInTheDocument()
    expect(screen.getByText('Proposed by you')).toBeInTheDocument()
  })

  it('surfaces the reason a decision was refused', async () => {
    // WHERE THE INTERESTING REFUSALS LAND: a four-eyes rule rejecting
    // a self-approval, or a write whose field the ontology no longer
    // declares. Both are decisions the server made for a stated
    // reason, and a generic failure would waste it.
    mockedList.mockResolvedValue([write()])
    mockedConfirm.mockRejectedValue(new Error('approved by someone other than its proposer'))
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Approve' }))

    await waitFor(() => expect(screen.getByText(/other than its proposer/)).toBeInTheDocument())
  })

  it('does not fetch the diff until a row is opened', async () => {
    // A diff is a permission-checked read per field per object. Doing
    // it for every row would cost hundreds of reads to render a queue
    // somebody is scanning rather than reading.
    mockedList.mockResolvedValue([write()])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText(/Change which category/)
    expect(mockedDetail).not.toHaveBeenCalled()
  })

  it('fetches the diff when a row is opened', async () => {
    mockedList.mockResolvedValue([write()])
    mockedDetail.mockResolvedValue({
      write_id: 'w1',
      action_type_name: 'A',
      description: 'd',
      proposed_by: 'alice',
      proposed_at: 't',
      expires_at: 't',
      awaiting_your_review: true,
      proposed_by_you: false,
      objects: [],
      has_redacted_fields: false,
    })
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'View changes' }))

    await waitFor(() => expect(mockedDetail).toHaveBeenCalledWith('w1'))
  })
})

describe('a write the configuration has outrun', () => {
  /**
   * HOT_RELOAD_PLAN.md step 6c. A write whose field the ontology no
   * longer declares CANNOT be approved -- the unapplyable check
   * refuses it. Before this, the inbox still offered an Approve
   * button: a reviewer made a decision, learned it was refused, and
   * had gained nothing.
   *
   * A DIFFERENT STATE FROM REJECTED. Rejected means a human decided
   * against it; this means nobody can act on it either way.
   */
  it('does not offer Approve', async () => {
    mockedList.mockResolvedValue([write({ undeclared_fields: ['Customer.name'] })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText(/Change which category/)
    expect(screen.queryByRole('button', { name: 'Approve' })).toBeNull()
  })

  it('still offers Reject', async () => {
    // A reviewer needs to clear it out of the queue. Rejection is
    // deliberately never blocked by the unapplyable check -- otherwise
    // a proposal nobody can act on sits there until its TTL.
    mockedList.mockResolvedValue([write({ undeclared_fields: ['Customer.name'] })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Reject' })).toBeInTheDocument()
  })

  it('says so rather than looking ordinary', async () => {
    mockedList.mockResolvedValue([write({ undeclared_fields: ['Customer.name'] })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('Cannot be applied')).toBeInTheDocument()
  })

  it('replaces the invitation rather than sitting beside it', async () => {
    // Both can be true -- you may hold the grant AND the write may be
    // impossible -- and showing "Awaiting your review" next to "Cannot
    // be applied" invites a decision that cannot be carried out.
    mockedList.mockResolvedValue([write({ undeclared_fields: ['Customer.name'] })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('Cannot be applied')
    expect(screen.queryByText('Awaiting your review')).toBeNull()
  })

  it('leaves an ordinary write alone', async () => {
    // THE CONTROL. A panel that hid Approve unconditionally would pass
    // every test above while making the feature useless.
    mockedList.mockResolvedValue([write()])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument()
    expect(screen.queryByText('Cannot be applied')).toBeNull()
  })
})

describe('identical proposals', () => {
  /**
   * Three identical rows appeared in a real inbox with no way to tell
   * one mistake pasted three times from three separate requests.
   *
   * SURFACED, NOT DEDUPLICATED. The reviewer is the one who can tell a
   * double-click from a deliberate re-request; the server cannot.
   */
  it('says how many others propose the same change', async () => {
    mockedList.mockResolvedValue([write({ duplicate_count: 2 })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('2 identical proposals')).toBeInTheDocument()
  })

  it('reads correctly for a single duplicate', async () => {
    // "1 identical proposals" is the kind of thing that makes a
    // product look unfinished at exactly the moment someone is
    // deciding whether to trust it.
    mockedList.mockResolvedValue([write({ duplicate_count: 1 })])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('1 identical proposal')).toBeInTheDocument()
  })

  it('says nothing when a proposal is unique', async () => {
    // THE CONTROL. A tag shown always is a tag nobody reads, and most
    // proposals are unique.
    mockedList.mockResolvedValue([write()])
    render(<ApprovalsPanel onSessionExpired={vi.fn()} />)

    await screen.findByText(/Change which category/)
    expect(screen.queryByText(/identical proposal/)).toBeNull()
  })
})
