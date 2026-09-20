/**
 * What the mirror holds, table by table.
 *
 * WE BUILT AN INTEGRITY GUARANTEE AND LEFT IT INVISIBLE. A value that
 * cannot be coerced fails the whole table's sync, silver keeps its
 * previous snapshot, and bronze accepts the bad value so it can be
 * diagnosed. The only trace was stderr on whatever ran the sync.
 *
 * THE DIVERGENCE IS THE FINDING. Bronze took rows that silver refused
 * to interpret, so a gap between the two counts means the last sync
 * was rejected and what is being served is the snapshot before it.
 * Proven against a real mirror: a good sync leaves (2, 2), a refused
 * one leaves (2, 4).
 */

import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MirrorPanel from './MirrorPanel'

vi.mock('@elysium/shell-api/api', () => ({
  getMirrorState: vi.fn(),
  getErrorMessage: (error: unknown) => String((error as Error)?.message ?? error),
  handleIfSessionExpired: () => false,
}))

const { getMirrorState } = await import('@elysium/shell-api/api')
const mocked = vi.mocked(getMirrorState)

function table(overrides = {}) {
  return {
    silo: 'primary_sql',
    table: 'transactions',
    last_synced_at: new Date().toISOString(),
    silver_rows: 7,
    bronze_rows: 7,
    last_attempt_at: new Date().toISOString(),
    last_attempt_outcome: 'synced',
    last_attempt_detail: null,
    snapshots: [],
    ...overrides,
  }
}

beforeEach(() => {
  mocked.mockReset()
})

describe('a healthy mirror', () => {
  it('shows each table and both row counts', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('primary_sql.transactions')).toBeInTheDocument()
    expect(screen.getAllByText('7')).toHaveLength(2)
  })

  it('says nothing about a refused sync when there was none', async () => {
    // THE CONTROL. A warning on every row would be ignored by the time
    // it mattered.
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')
    expect(screen.queryByText(/was refused/)).toBeNull()
  })
})

describe('a refused sync', () => {
  it('names the gap rather than leaving two numbers to compare', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ silver_rows: 2, bronze_rows: 4 })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/was refused/)).toBeInTheDocument()
  })

  it('says the OTHER thing when silver is simply out of date', async () => {
    /** THE DIRECTION SAYS WHICH FAULT IT IS, and a first version said
     *  "fetched but not served" for both.
     *
     *  Seen on a real deployment: 67 served against 7 fetched, where
     *  nothing had been dropped. Bronze held the current source and
     *  silver held a snapshot from before it shrank -- because the
     *  sync that would have shrunk silver had been refused.
     */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ silver_rows: 67, bronze_rows: 7 })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/out of date/)).toBeInTheDocument()
    expect(screen.queryByText(/fetched but not served/)).toBeNull()
  })

  it('says WHY the last sync was refused', async () => {
    /** THE THING SOMEBODY OPENED THIS SCREEN TO FIND OUT.
     *
     * A refused sync leaves the previous snapshot, so from the
     * mirror's own timestamps it is indistinguishable from a source
     * that has not changed. The reason was only ever on stderr.
     */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [
        table({
          last_attempt_outcome: 'refused',
          last_attempt_detail: "column 'transaction_date' is declared 'date' but contains 'not-a-date'",
        }),
      ],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/not-a-date/)).toBeInTheDocument()
    expect(screen.getByText(/serving the snapshot from before it/)).toBeInTheDocument()
  })

  it('says nothing about a refusal when the last attempt succeeded', async () => {
    // THE CONTROL. A warning banner on a healthy mirror is one nobody
    // reads by the time it matters.
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')
    expect(screen.queryByText(/was refused/)).toBeNull()
  })

  it('does not claim a refusal when nothing was recorded', async () => {
    /** NOTHING RECORDED IS NOT A FAILURE. An existing deployment has
     *  no attempts until its next sync, and both "refused" and
     *  "never" would be wrong there. */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [
        table({
          last_attempt_at: null,
          last_attempt_outcome: null,
          last_attempt_detail: null,
        }),
      ],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('not recorded')).toBeInTheDocument()
    expect(screen.queryByText(/was refused/)).toBeNull()
  })

  it('shows integrity problems when the check found some', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: ['bronze_primary_sql.customers: could not be read'],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/could not be read/)).toBeInTheDocument()
  })
})

describe("a table's recent changes", () => {
  it('lists them when there are some', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [
        table({
          snapshots: [
            { at: new Date().toISOString(), operation: 'APPEND', rows: 7, current: true },
            { at: new Date().toISOString(), operation: 'DELETE', rows: 0, current: false },
          ],
        }),
      ],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/2 recent changes/)).toBeInTheDocument()
  })

  it('says nothing when a table has no history', async () => {
    // THE CONTROL. A table with no snapshots should show no history
    // row at all rather than an empty one.
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ snapshots: [] })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')
    expect(screen.queryByText(/recent change/)).toBeNull()
  })

  it('marks which one is being served', async () => {
    /** A HISTORY WITHOUT A CURRENT MARKER is a list of dates. The
     *  point of showing it is knowing where you are in it -- which is
     *  also what a rollback would need. */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [
        table({
          snapshots: [{ at: new Date().toISOString(), operation: 'APPEND', rows: 7, current: true }],
        }),
      ],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/serving now/)).toBeInTheDocument()
  })
})

describe('a table that has never synced', () => {
  it('says never rather than showing an empty cell', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ last_synced_at: null, silver_rows: null, bronze_rows: null })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('never synced')).toBeInTheDocument()
  })
})

describe('a deployment reading live', () => {
  it('says so instead of showing an empty table', async () => {
    // NOT AN ERROR, and not a blank page that looks like a broken
    // sync: a live deployment simply has no mirror state.
    mocked.mockResolvedValue({
      reading_from_mirror: false,
      tables: [],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/reads live/i)).toBeInTheDocument()
  })
})

describe('while the page is open', () => {
  it('refreshes without a reload', async () => {
    /** AN ADMINISTRATOR WATCHING DURING AN INCIDENT should see the
     *  screen change rather than wonder whether to reload.
     *
     *  This is the EASY case. The hard one is nobody looking at all,
     *  which polling cannot fix and notification can -- see
     *  TRIGGERS_AND_PLUGINS.md.
     */
    vi.useFakeTimers()
    try {
      mocked.mockResolvedValue({
        reading_from_mirror: true,
        tables: [table()],
        problems: [],
      })
      render(<MirrorPanel onSessionExpired={vi.fn()} />)

      await vi.advanceTimersByTimeAsync(31_000)

      expect(mocked.mock.calls.length).toBeGreaterThan(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it('stops when the panel goes away', async () => {
    // A TIMER THAT OUTLIVES ITS COMPONENT keeps requesting forever and
    // sets state on something unmounted.
    vi.useFakeTimers()
    try {
      mocked.mockResolvedValue({
        reading_from_mirror: true,
        tables: [table()],
        problems: [],
      })
      const { unmount } = render(<MirrorPanel onSessionExpired={vi.fn()} />)
      unmount()
      const after = mocked.mock.calls.length

      await vi.advanceTimersByTimeAsync(90_000)

      expect(mocked.mock.calls.length).toBe(after)
    } finally {
      vi.useRealTimers()
    }
  })
})

describe('when the request fails', () => {
  it('reports rather than rendering nothing', async () => {
    mocked.mockRejectedValue(new Error('mirror unreachable'))
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText(/mirror unreachable/)).toBeInTheDocument()
    })
  })
})
