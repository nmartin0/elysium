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

describe('when the request fails', () => {
  it('reports rather than rendering nothing', async () => {
    mocked.mockRejectedValue(new Error('mirror unreachable'))
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await waitFor(() => {
      expect(screen.getByText(/mirror unreachable/)).toBeInTheDocument()
    })
  })
})
