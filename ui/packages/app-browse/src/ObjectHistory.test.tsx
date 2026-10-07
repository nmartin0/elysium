import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'

const getObjectHistory = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getObjectHistory: () => getObjectHistory() }
})

const { default: ObjectHistory } = await import('./ObjectHistory')

/**
 * The fixture matches the endpoint's own response model -- entries,
 * total, next_page_token -- rather than a shape I assumed. A fixture
 * that does not match the API is a test that proves nothing about
 * production, which is how the graph shipped a white screen.
 */
const BODY = {
  entries: [
    {
      id: 'w1',
      operation: 'update',
      changes: { risk_score: 0.9 },
      user_id: 'alice',
      description: 'Raised risk',
      created_at: '2026-09-07T10:00:00Z',
    },
  ],
  total: 1,
  next_page_token: null,
}

beforeEach(() => {
  vi.clearAllMocks()
  getObjectHistory.mockResolvedValue(BODY)
})

const props = { objectType: 'Customer', objectId: 'c1', onSessionExpired: () => {} }

describe('ObjectHistory', () => {
  it('says who changed what, and when', async () => {
    render(<ObjectHistory {...props} />)

    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText('update')).toBeInTheDocument()
    expect(screen.getByText(/Risk score/)).toBeInTheDocument()
  })

  it('shows the raw timestamp, not a relative one', async () => {
    /**
     * "2 hours ago" reads well and is useless in an audit context,
     * where the question is usually "was this before or after X".
     */
    render(<ObjectHistory {...props} />)

    expect(await screen.findByText('2026-09-07T10:00:00Z')).toBeInTheDocument()
  })

  it('says so when nothing has been edited', async () => {
    // The ordinary case, and it deserves a sentence rather than an
    // empty table.
    getObjectHistory.mockResolvedValue({ entries: [], total: 0, next_page_token: null })

    render(<ObjectHistory {...props} />)

    expect(await screen.findByText(/No recorded changes/)).toBeInTheDocument()
  })

  it('reports a failure rather than an empty panel', async () => {
    getObjectHistory.mockRejectedValue(new Error('history unavailable'))

    render(<ObjectHistory {...props} />)

    expect(await screen.findByText(/history unavailable/)).toBeInTheDocument()
  })

  it('renders whatever fields the server sent, without filtering', async () => {
    /**
     * Authorization is the SERVER'S. The mediator filters out fields
     * the reader cannot see and drops an entry that empties, so
     * "someone changed something" never reaches here -- and this file
     * doing its own filtering would be a second place for that rule to
     * live and drift.
     */
    getObjectHistory.mockResolvedValue({
      entries: [{ ...BODY.entries[0]!, changes: { a: 1, b: 2 } }],
      total: 1,
      next_page_token: null,
    })

    render(<ObjectHistory {...props} />)

    expect(await screen.findByText(/A, B/)).toBeInTheDocument()
  })
})

describe('an entry whose fields are all unreadable', () => {
  it('still appears, and says why it is empty', async () => {
    /**
     * The server's rule, quoted in the mediator: an entry whose
     * changes are entirely ungranted STILL APPEARS with empty changes,
     * "because the FACT that someone edited this object at a given
     * time is exactly what an audit trail is for".
     *
     * So hiding it would defeat the reason it is sent. And leaving the
     * cell blank reads as a rendering fault rather than a deliberate
     * boundary -- I had written a comment claiming the server dropped
     * these, which would have made an empty row look like a bug.
     */
    getObjectHistory.mockResolvedValue({
      entries: [{ ...BODY.entries[0]!, changes: {} }],
      total: 1,
      next_page_token: null,
    })

    render(<ObjectHistory {...props} />)

    expect(await screen.findByText('alice')).toBeInTheDocument()
    expect(screen.getByText(/cannot read/)).toBeInTheDocument()
  })
})

describe('an edit that was part of a bulk action', () => {
  /**
   * The server sends `batch_id` for a stated reason -- "so a UI can
   * group the writes that happened together; Foundry links a single
   * action log to every object it edited for the same reason" -- and no
   * UI used it. `getObjectHistory` returns `Promise<unknown>`, so this
   * component's local interface was the only declaration of the shape,
   * and it simply omitted the field.
   */

  it('says so, rather than reading as an isolated edit', async () => {
    /** Without this, a sweep touching fifty objects leaves fifty
     *  unrelated-looking rows in fifty histories, and "why did this
     *  change" cannot distinguish a deliberate bulk action from
     *  somebody editing records one at a time. */
    getObjectHistory.mockResolvedValue({
      ...BODY,
      entries: [{ ...BODY.entries[0], batch_id: 'b-42' }],
    })
    render(<ObjectHistory {...props} />)

    expect(await screen.findByText('part of a bulk action')).toBeInTheDocument()
  })

  it('says nothing for an ordinary single edit', async () => {
    /** A marker on every row would be noise, and noise is how a real
     *  signal gets ignored. */
    render(<ObjectHistory {...props} />)

    await screen.findByText('alice')
    expect(screen.queryByText('part of a bulk action')).not.toBeInTheDocument()
  })

  it('treats a null batch_id as no batch', async () => {
    /** The field is `str | None` on the server. Null must mean "not part
     *  of one", not an unknown rendered as a marker. */
    getObjectHistory.mockResolvedValue({
      ...BODY,
      entries: [{ ...BODY.entries[0], batch_id: null }],
    })
    render(<ObjectHistory {...props} />)

    await screen.findByText('alice')
    expect(screen.queryByText('part of a bulk action')).not.toBeInTheDocument()
  })

  it('does not claim how many other objects were touched', async () => {
    /** The history endpoint answers for ONE object. Counting the rest
     *  would mean counting objects this reader may not be allowed to
     *  see, so the marker states the fact and stops. */
    getObjectHistory.mockResolvedValue({
      ...BODY,
      entries: [{ ...BODY.entries[0], batch_id: 'b-42' }],
    })
    const { container } = render(<ObjectHistory {...props} />)

    await screen.findByText('part of a bulk action')
    expect(container.textContent).not.toContain('b-42')
    expect(container.textContent).not.toMatch(/\d+ other/)
  })
})
