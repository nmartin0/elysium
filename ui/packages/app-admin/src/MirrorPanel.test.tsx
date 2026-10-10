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

import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import MirrorPanel, { formatShare, quarantineShare, readingFor } from './MirrorPanel'

vi.mock('@elysium/shell-api/api', () => ({
  getMirrorState: vi.fn(),
  startMirrorSync: vi.fn(),
  getErrorMessage: (error: unknown) => String((error as Error)?.message ?? error),
  handleIfSessionExpired: () => false,
}))

const { getMirrorState, startMirrorSync } = await import('@elysium/shell-api/api')
const mockedSync = vi.mocked(startMirrorSync)
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
    quarantined_rows: 0,
    quarantine_reason: null,
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

  it('says how many rows were held back, and why', async () => {
    /**
     * OPEN_RISKS item 1, and GOLD-3d. A quarantined row is absent from
     * silver BY DESIGN, and absence reads as loss: 2 served against 4
     * fetched says nothing about whether 2 were rejected on purpose,
     * dropped by a bug, or never existed. The server has sent
     * quarantined_rows and quarantine_reason all along; nothing read
     * them, and MirrorTableState did not even declare them.
     */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [
        table({
          silver_rows: 2,
          bronze_rows: 4,
          quarantined_rows: 2,
          quarantine_reason: "'N/A' is not an integer",
        }),
      ],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/2 held back/)).toBeInTheDocument()
    expect(screen.getByText(/'N\/A' is not an integer/)).toBeInTheDocument()
  })

  it('does not call a fully explained gap a refusal', async () => {
    /**
     * THE CORRECTION, and the reason this is not just a new column.
     * The existing tag says "fetched but not served -- the last sync
     * was refused" for ANY bronze/silver gap. When the gap is exactly
     * what validation held back, nothing was refused: the sync worked
     * and did its job. Telling an admin their sync was refused sends
     * them looking for an incident that did not happen.
     */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ silver_rows: 2, bronze_rows: 4, quarantined_rows: 2, quarantine_reason: 'bad dates' })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/2 held back/)).toBeInTheDocument()
    expect(screen.queryByText(/was refused/)).not.toBeInTheDocument()
  })

  it('still names a refusal when quarantine explains only part of the gap', async () => {
    // 5 fetched, 2 served, 1 quarantined: two rows are unaccounted
    // for, which IS the refused-sync state and must still be said.
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ silver_rows: 2, bronze_rows: 5, quarantined_rows: 1, quarantine_reason: 'bad dates' })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/was refused/)).toBeInTheDocument()
    expect(screen.getByText(/1 held back/)).toBeInTheDocument()
  })

  it('says nothing about quarantine when nothing was held back', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table({ silver_rows: 7, bronze_rows: 7, quarantined_rows: 0 })],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('primary_sql.transactions')).toBeInTheDocument()
    expect(screen.queryByText(/held back/)).not.toBeInTheDocument()
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

describe('starting a sync', () => {
  it('reports what the server said', async () => {
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    mockedSync.mockResolvedValue({
      started: true,
      detail: 'A sync is running.',
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')
    fireEvent.click(screen.getByRole('button', { name: /sync now/i }))

    expect(await screen.findByText(/A sync is running/)).toBeInTheDocument()
  })

  it('says nothing before the button is pressed', async () => {
    // THE CONTROL. A message rendered unconditionally would pass the
    // test above while telling every visitor a sync was running.
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')

    expect(screen.queryByText(/A sync is running/)).toBeNull()
  })

  it('shows the failure rather than swallowing it', async () => {
    /** A BUTTON THAT DOES NOTHING VISIBLE on failure is one somebody
     *  presses repeatedly. */
    mocked.mockResolvedValue({
      reading_from_mirror: true,
      tables: [table()],
      problems: [],
    })
    mockedSync.mockRejectedValue(new Error('this deployment reads live'))
    render(<MirrorPanel onSessionExpired={vi.fn()} />)

    await screen.findByText('primary_sql.transactions')
    fireEvent.click(screen.getByRole('button', { name: /sync now/i }))

    expect(await screen.findByText(/reads live/)).toBeInTheDocument()
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

describe('the quarantine rate per rule', () => {
  /**
   * DEV_UI.md 16.4's DISTRIBUTION pillar, which it calls the one
   * Elysium is furthest from: "the quarantine RATE per rule: 0.1% is
   * a data problem, 40% is a pipeline problem (the owner's D4
   * decision)". Tested as arithmetic rather than through the DOM
   * because jsdom computes nothing and a wrong denominator renders
   * perfectly.
   */
  it('divides by what was FETCHED, not by what was served', () => {
    /** Bronze is everything the source gave; silver is what survived.
     *  Dividing by silver compares the held-back rows against the
     *  ones that were not held back, and reports over 100% for a
     *  table mostly rejected. */
    expect(quarantineShare(12, 1200)).toBeCloseTo(0.01)
    expect(quarantineShare(12, 12)).toBe(1)
  })

  it('has no rate when there is nothing to divide by', () => {
    expect(quarantineShare(3, null)).toBeNull()
    expect(quarantineShare(3, undefined)).toBeNull()
    expect(quarantineShare(3, 0)).toBeNull()
  })

  it('keeps two decimals below one percent, because D4 turns on 0.1%', () => {
    /** Rounding 0.1% to "0%" would erase the exact distinction the
     *  number exists to draw. */
    expect(formatShare(0.001)).toBe('0.10%')
    expect(formatShare(0.004)).toBe('0.40%')
  })

  it('rounds to whole percents above one, where a decimal is noise', () => {
    expect(formatShare(0.4)).toBe('40%')
    expect(formatShare(0.125)).toBe('13%')
  })
})

describe('the reading put on a rate', () => {
  it('calls a rule that caught most of the table a pipeline problem', () => {
    expect(readingFor(0.4)).toContain('not the data')
    expect(readingFor(0.9)).toContain('not the data')
  })

  /**
   * ONLY THE LOUD END IS LABELLED. D4 decided two points and said
   * nothing between them, so a verdict on 12% would be a threshold
   * nobody set -- and DEV_UI.md 16.2 is blunt that invented
   * thresholds are how a channel stops being read.
   */
  it('says nothing about a rate in the range D4 did not decide', () => {
    expect(readingFor(0.12)).toBeNull()
    expect(readingFor(0.39)).toBeNull()
  })

  it('says nothing about an ordinary data problem, which is a rule working', () => {
    /** Annotating the normal case would make a working deployment
     *  read as a broken one. */
    expect(readingFor(0.001)).toBeNull()
  })

  it('says nothing when there is no rate at all', () => {
    expect(readingFor(null)).toBeNull()
  })
})

describe('the rules that held rows back, on screen', () => {
  function held(overrides = {}) {
    return table({
      silver_rows: 2,
      bronze_rows: 12,
      quarantined_rows: 10,
      quarantine_reason: 'is required, and missing',
      quarantine_rules: [
        { column: 'email', reason: 'is required, and missing', rows: 7 },
        { column: 'region', reason: 'is required, and missing', rows: 3 },
      ],
      quarantine_last_detected_at: '2026-09-24T00:00:00.000Z',
      ...overrides,
    })
  }

  function show(rows = [held()]) {
    mocked.mockResolvedValue({ reading_from_mirror: true, tables: rows, problems: [] })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)
  }

  /**
   * THE GAP THIS CLOSES. The tag beside the row count names the
   * loudest rule, which is enough to know something is firing and not
   * enough to act: this table declares the SAME rule on two columns,
   * so that tag reads identically whichever one is at fault.
   */
  it('names every rule, not only the loudest', async () => {
    show()

    expect(await screen.findByText('email')).toBeInTheDocument()
    expect(screen.getByText('region')).toBeInTheDocument()
  })

  it('says how many rows each rule caught', async () => {
    show()
    await screen.findByText('email')

    const breakdown = document.querySelector('.mirror__quarantine')?.textContent ?? ''

    expect(breakdown).toContain('7 rows')
    expect(breakdown).toContain('3 rows')
  })

  it('says what share of the fetched rows each caught', async () => {
    // 7 of 12 and 3 of 12. The count alone reads the same at any
    // table size; the share is what separates a handful of bad
    // records from a broken rule.
    show()
    await screen.findByText('email')

    const breakdown = document.querySelector('.mirror__quarantine')?.textContent ?? ''

    expect(breakdown).toContain('58%')
    expect(breakdown).toContain('25%')
  })

  it('calls the loud one a pipeline problem, and leaves the other alone', async () => {
    // 58% is past D4's 40%; 25% is in the range D4 did not decide.
    show()
    await screen.findByText('email')

    expect(screen.getAllByText(/not the data/)).toHaveLength(1)
  })

  it('says when a rule last fired, so a standing count reads differently from a new one', async () => {
    show()

    expect(await screen.findByText(/rules holding rows back/)).toHaveTextContent('last at')
  })

  it('counts the rules in the summary, so it need not be opened to be useful', async () => {
    show()

    expect(await screen.findByText(/2 rules holding rows back/)).toBeInTheDocument()
  })

  it('says rule, singular, when there is one', async () => {
    show([held({ quarantine_rules: [{ column: 'email', reason: 'is required, and missing', rows: 7 }] })])

    expect(await screen.findByText(/1 rule holding rows back/)).toBeInTheDocument()
  })

  /**
   * THE CONTROL. A breakdown on every row would be ignored by the time
   * one mattered, and a healthy deployment must not look like a sick
   * one.
   */
  it('renders no breakdown at all when nothing was held back', async () => {
    show([table()])
    await screen.findByText('primary_sql.transactions')

    expect(document.querySelector('.mirror__quarantine')).toBeNull()
  })

  it('still lists the rules when the fetched count is unknown, just without a share', async () => {
    // A rate needs a denominator; a rule name does not, and dropping
    // the rule because the count is missing would hide the finding.
    show([held({ bronze_rows: null })])
    await screen.findByText('email')

    const breakdown = document.querySelector('.mirror__quarantine')?.textContent ?? ''

    expect(breakdown).toContain('7 rows')
    expect(breakdown).not.toContain('%')
  })

  /**
   * THERE IS NO TEST HERE THAT A VALUE DOES NOT REACH THE SCREEN, and
   * the absence is deliberate rather than an oversight.
   *
   * A row quarantined for its CONTENT often failed on the sensitive
   * part of it -- a malformed national insurance number is still a
   * national insurance number -- so no value may be rendered. But
   * `QuarantineRule` has no value field, so a test asserting one is
   * absent from the DOM would pass against a fixture that never
   * contained one. That is a test that cannot fail, which this
   * project has shipped before and which proves nothing.
   *
   * THE GUARANTEE IS ENFORCED WHERE IT CAN FAIL: the server, by
   * `test_no_VALUE_reaches_the_panel` in
   * tests/integration/test_mirror_sync_endpoint.py, which puts a real
   * value in the lake and asserts it is nowhere in the response. A
   * value cannot reach this panel because it never leaves the
   * process that holds it.
   */
})

describe('the rules that warned rather than held', () => {
  function warned(overrides = {}) {
    return table({
      silver_rows: 12,
      bronze_rows: 12,
      expectation_warnings: [
        { column: 'email', reason: 'does not match the declared pattern', rows: 4 },
        { column: 'region', reason: 'is not one of the declared values', rows: 1 },
      ],
      ...overrides,
    })
  }

  function show(rows = [warned()]) {
    mocked.mockResolvedValue({ reading_from_mirror: true, tables: rows, problems: [] })
    render(<MirrorPanel onSessionExpired={vi.fn()} />)
  }

  /**
   * THE GAP THIS CLOSES. `warn` keeps the row, so unlike a quarantined
   * one it leaves no gap in the counts and no finding in the lake --
   * the rule reached a log line on whatever ran the sync and stopped
   * there. DEV_UI.md 5.6 asks for "failing expectations" beside the
   * quarantined rows.
   */
  it('names every rule that warned', async () => {
    show()

    expect(await screen.findByText('email')).toBeInTheDocument()
    expect(screen.getByText('region')).toBeInTheDocument()
  })

  it('says how many rows each kept', async () => {
    show()
    await screen.findByText('email')

    const warnings = document.querySelector('.mirror__warnings')?.textContent ?? ''

    expect(warnings).toContain('4 rows kept')
    expect(warnings).toContain('1 row kept')
  })

  /**
   * KEPT, NOT HELD, and the word carries the whole distinction. A
   * reader who takes a warning for a quarantine will go looking for
   * rows that are not missing.
   */
  it('says the rows were KEPT, since that is what warn means', async () => {
    show()
    await screen.findByText('email')

    const warnings = document.querySelector('.mirror__warnings')?.textContent ?? ''

    expect(warnings).toContain('kept')
    expect(warnings).not.toContain('held back')
  })

  /**
   * NO SHARE. A rate exists to say whether an absence is a data
   * problem or a pipeline one; nothing is absent here, so the question
   * does not arise and a percentage would invite it.
   */
  it('puts no percentage on a rule that took nothing away', async () => {
    show()
    await screen.findByText('email')

    expect(document.querySelector('.mirror__warnings')?.textContent ?? '').not.toContain('%')
  })

  it('says it was the last sync, not all time', async () => {
    show()

    expect(await screen.findByText(/warned on the last sync/)).toBeInTheDocument()
  })

  it('says rule, singular, when there is one', async () => {
    show([warned({ expectation_warnings: [{ column: 'email', reason: 'is odd', rows: 4 }] })])

    expect(await screen.findByText(/1 rule warned on the last sync/)).toBeInTheDocument()
  })

  /** THE CONTROL. A healthy deployment must not look like a sick one. */
  it('renders nothing at all when no rule warned', async () => {
    show([table()])
    await screen.findByText('primary_sql.transactions')

    expect(document.querySelector('.mirror__warnings')).toBeNull()
  })

  /**
   * THE TWO ARE DIFFERENT THINGS AND THE PANEL KEEPS THEM APART. One
   * says why a row is missing, the other why a row is present and
   * suspect -- merging them would make "how many rows are not here"
   * unanswerable.
   */
  it('keeps the warned rules in a separate section from the held ones', async () => {
    show([
      warned({
        quarantined_rows: 2,
        quarantine_reason: 'is required, and missing',
        quarantine_rules: [{ column: 'name', reason: 'is required, and missing', rows: 2 }],
      }),
    ])
    await screen.findByText('email')

    const held = document.querySelector('.mirror__quarantine')?.textContent ?? ''
    const warnings = document.querySelector('.mirror__warnings')?.textContent ?? ''

    expect(held).toContain('name')
    expect(held).not.toContain('email')
    expect(warnings).toContain('email')
    expect(warnings).not.toContain('name')
  })
})
