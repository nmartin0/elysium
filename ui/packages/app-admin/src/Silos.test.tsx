import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, within } from '@testing-library/react'

const getSilos = vi.fn()
const getDataFreshness = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getSilos: () => getSilos(), getDataFreshness: () => getDataFreshness() }
})

const { default: Silos } = await import('./Silos')

const HEALTHY = [
  {
    name: 'primary_sql',
    adapter: 'sqlite',
    object_types: ['Customer'],
    // OF THOSE, THE ONES IT IS PRIMARY FOR. Carried since R6: "backs
    // Customer" and "IS Customer" are different outages and the
    // payload used to collapse them.
    primary_for: ['Customer'],
    reachable: true,
    failure: null,
    fields: [
      { object_type: 'Customer', field: 'name', column: 'name', table: 'customers', is_identifier: false },
      { object_type: 'Customer', field: 'customer_id', column: 'customer_id', table: 'customers', is_identifier: true },
    ],
  },
  {
    name: 'support_crm',
    adapter: 'sqlite',
    object_types: ['Ticket'],
    primary_for: ['Ticket'],
    reachable: true,
    failure: null,
    fields: [
      { object_type: 'Ticket', field: 'risk_score', column: 'score_val', table: 'customer_risk', is_identifier: false },
      { object_type: 'Ticket', field: 'customer_id', column: 'cust_ref', table: 'customer_risk', is_identifier: true },
    ],
  },
]

beforeEach(() => {
  vi.clearAllMocks()
  getSilos.mockResolvedValue(HEALTHY)
  getDataFreshness.mockResolvedValue({
    source: 'gold',
    last_synced_at: null,
    published_at: { Customer: new Date(Date.now() - 60 * 60_000).toISOString(), Ticket: new Date().toISOString() },
  })
})

describe('Silos', () => {
  it('answers "is anything wrong" before listing anything', async () => {
    // A table of green rows makes you read every one to find that out.
    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText(/All 2 silos are reachable/)).toBeInTheDocument()
  })

  it('names what is not answering', async () => {
    getSilos.mockResolvedValue([HEALTHY[0], { ...HEALTHY[1], reachable: false, failure: 'FileNotFoundError' }])

    render(<Silos onSessionExpired={() => {}} />)

    // SCOPED TO THE SUMMARY, for the reason the test below already
    // records about 'Customer': a bare /not answering/ matched once
    // when this was the only thing that said it. The per-type health
    // column now says it too, about the same outage, which makes the
    // unscoped query ambiguous rather than wrong -- it only ever had
    // one possible answer.
    expect(await screen.findByRole('heading', { name: 'Some silos are not answering' })).toBeInTheDocument()
    expect(screen.getByText('FileNotFoundError')).toBeInTheDocument()
  })

  it('shows which object types each silo backs', async () => {
    // The operational question when one is down: what stops working.
    //
    // SCOPED TO THE SILO TABLE. A bare getByText('Customer') matched
    // once when this was the only table on the panel; the publication
    // table added beside it names the same types, for a different
    // reason. Asking the page was always ambiguous -- it just had only
    // one possible answer.
    render(<Silos onSessionExpired={() => {}} />)

    const table = await screen.findByRole('table', { name: 'Silos and the object types they back' })
    expect(within(table).getByText('Customer')).toBeInTheDocument()
    expect(within(table).getByText('Ticket')).toBeInTheDocument()
  })

  it('reports a failure rather than an empty screen', async () => {
    getSilos.mockRejectedValue(new Error('silos unavailable'))

    render(<Silos onSessionExpired={() => {}} />)

    expect(await screen.findByText(/silos unavailable/)).toBeInTheDocument()
  })
})

describe('Silos -- the fields behind a silo', () => {
  it('hides field detail until asked', async () => {
    // A silo list is read to answer "is anything wrong". Field detail
    // is the follow-up question, and showing it always would bury the
    // answer to the first one.
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')

    expect(screen.queryByText('customers')).not.toBeInTheDocument()
  })

  it('shows the physical table and column on expand', async () => {
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')

    fireEvent.click(screen.getByLabelText(/Show fields backed by primary_sql/))

    // getAllByText: the identifier row shares the table name, which is
    // correct -- both live in `customers`.
    // Both getAllByText: a field name can equal its column name (name
    // -> name), and the identifier row shares the table, so single
    // queries find several. The assertion is that the detail appeared.
    expect(screen.getAllByText('customers').length).toBeGreaterThan(0)
    expect(screen.getAllByText('name').length).toBeGreaterThan(0)
  })

  it('marks a column whose name differs from its field', async () => {
    /**
     * The case worth noticing. Customer.risk_score reads a column
     * called score_val, and when a query returns something unexpected
     * that mismatch is exactly what you are looking for -- so it is
     * marked rather than left to be spotted by comparing two columns.
     */
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('support_crm')

    fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))

    expect(screen.getByText('score_val')).toBeInTheDocument()
    // Two renamings in this silo now -- score_val and cust_ref -- so
    // the assertion is that renaming is marked at all, not that it
    // happens once.
    expect(screen.getAllByText(/renamed/).length).toBeGreaterThan(0)
  })

  it('collapses again', async () => {
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('primary_sql')
    fireEvent.click(screen.getByLabelText(/Show fields backed by primary_sql/))

    fireEvent.click(screen.getByLabelText(/Hide fields backed by primary_sql/))

    expect(screen.queryByText('customers')).not.toBeInTheDocument()
  })
})

describe('Silos -- the join key', () => {
  it('marks the identifier and shows its renaming', async () => {
    /**
     * The mismatch that matters more than a renamed data column: a
     * wrong join key returns NOTHING, or another object's row, rather
     * than a wrong value.
     */
    render(<Silos onSessionExpired={() => {}} />)
    await screen.findByText('support_crm')

    fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))

    expect(screen.getByText('identifier')).toBeInTheDocument()
    expect(screen.getByText('cust_ref')).toBeInTheDocument()
  })

  it('separates the tag from the field name in the TEXT, not just visually', () => {
    /**
     * A CSS margin separates them on screen and leaves the DOM text as
     * "customer_ididentifier" -- which is what a screen reader
     * announces and what a copy-paste produces. Found in a paste of
     * the real screen.
     */
    render(<Silos onSessionExpired={() => {}} />)

    return screen.findByText('support_crm').then(() => {
      fireEvent.click(screen.getByLabelText(/Show fields backed by support_crm/))
      const cell = screen.getByText('identifier').closest('td')
      expect(cell?.textContent).not.toMatch(/customer_ididentifier/)
      expect(cell?.textContent).toMatch(/customer_id identifier/)
    })
  })
})

describe('what has been published, beside what it came from', () => {
  /**
   * GOLD-3d. This panel is about SOURCES and stays that way, but a
   * silo answering tells you nothing about whether anything was
   * published from it -- and published gold is the only thing Elysium
   * reads. A silo can be green while every read of its types fails.
   */
  it('lists each backed type and when it was published', async () => {
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByRole('heading', { name: /published to gold/i })).toBeInTheDocument()

    const table = screen.getByRole('table', { name: 'Object types and when each was published' })
    expect(within(table).getByText('Customer')).toBeInTheDocument()
    expect(within(table).getByText('1 hour ago')).toBeInTheDocument()
  })

  it('says which types have NEVER been published, and what that costs', async () => {
    // THE HALF THAT MATTERS. A type backed by a silo but absent from
    // published_at is one whose reads FAIL. A table listing only what
    // IS published would be a page of reassuring green that omits the
    // failure.
    getDataFreshness.mockResolvedValue({
      source: 'gold',
      last_synced_at: null,
      published_at: { Customer: new Date().toISOString() },
    })
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/never been published/i)).toBeInTheDocument()
    expect(screen.getByText(/Reads of Ticket will fail/)).toBeInTheDocument()
  })

  it('warns for every unpublished type, not just the first', async () => {
    getDataFreshness.mockResolvedValue({ source: 'mirror', last_synced_at: null })
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Reads of Customer, Ticket will fail/)).toBeInTheDocument()
  })

  it('says nothing about publication when freshness cannot be read', async () => {
    // The two fetches are INDEPENDENT: a freshness failure must not
    // blank the silo table, which is what this panel is for.
    getDataFreshness.mockRejectedValue(new Error('nope'))
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText('primary_sql')).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: /published to gold/i })).not.toBeInTheDocument()
  })
})

describe('is THIS TYPE healthy -- R6, health indexed by object type', () => {
  /**
   * The silo table below has every input and indexes them by SILO, so
   * "is Customer healthy" costs one expansion per silo and some
   * arithmetic. This section is the same facts indexed by the thing
   * the reader came in asking about.
   *
   * THE VERB IS REFRESH, NOT READ. Every read is served from published
   * gold since GOLD-9 removed live reads, so a dead source breaks no
   * query -- it stops the values being replaced while they go on being
   * served.
   */

  /** risk_sql's real shape: primary for nothing, backing one field of
   *  a type whose primary storage is elsewhere. */
  const WITH_EXTRA_STORAGE = [
    ...HEALTHY,
    {
      name: 'risk_sql',
      adapter: 'sqlite',
      object_types: ['Customer'],
      primary_for: [],
      reachable: true,
      failure: null,
      fields: [
        {
          object_type: 'Customer',
          field: 'risk_score',
          column: 'score_val',
          table: 'customer_risk',
          is_identifier: false,
        },
        {
          object_type: 'Customer',
          field: 'customer_id',
          column: 'cust_ref',
          table: 'customer_risk',
          is_identifier: true,
        },
      ],
    },
  ]

  it('says every type is refreshing when every silo answers', async () => {
    // THE CONTROL. A column that always said "no" would pass the two
    // tests below and fail this one.
    render(<Silos onSessionExpired={vi.fn()} />)

    const table = await screen.findByRole('table', { name: 'Object types and when each was published' })
    expect(within(table).getAllByText('yes')).toHaveLength(2)
    expect(within(table).queryByText(/stopped refreshing/)).not.toBeInTheDocument()
  })

  it('names the ONE FIELD that stopped when additional storage is down', async () => {
    // THE CASE THE PAYLOAD COULD NOT EXPRESS. risk_sql backs Customer
    // and is primary for nothing: Customer keeps refreshing and
    // risk_score does not.
    getSilos.mockResolvedValue(
      WITH_EXTRA_STORAGE.map((silo) =>
        silo.name === 'risk_sql' ? { ...silo, reachable: false, failure: 'FileNotFoundError' } : silo,
      ),
    )
    render(<Silos onSessionExpired={vi.fn()} />)

    const table = await screen.findByRole('table', { name: 'Object types and when each was published' })
    expect(within(table).getByText('partly')).toBeInTheDocument()
    expect(within(table).getByText(/risk_score — risk_sql is not answering/)).toBeInTheDocument()
    // AND NOT THE JOIN KEY, which risk_sql also holds -- counting it
    // would make a one-field outage look like it took the identifier.
    expect(within(table).queryByText(/customer_id/)).not.toBeInTheDocument()
  })

  it('says the whole type stopped when its PRIMARY storage is down', async () => {
    getSilos.mockResolvedValue(
      WITH_EXTRA_STORAGE.map((silo) =>
        silo.name === 'primary_sql' ? { ...silo, reachable: false, failure: 'FileNotFoundError' } : silo,
      ),
    )
    render(<Silos onSessionExpired={vi.fn()} />)

    const table = await screen.findByRole('table', { name: 'Object types and when each was published' })
    expect(within(table).getByText('no')).toBeInTheDocument()
    // THE ROW SAYS ONLY WHAT IS SPECIFIC TO IT. The explanation is
    // identical for every affected type and is said once, above the
    // table -- see the test below.
    expect(within(table).getByText('primary_sql is not answering')).toBeInTheDocument()
  })

  it('says what is being served meanwhile, rather than that reads fail', async () => {
    // THE FALSE ALARM THIS WORDING EXISTS TO AVOID. A dead source
    // breaks no query -- gold still answers every one of them -- so
    // "cannot be read" would send somebody hunting an outage their
    // users are not experiencing.
    getSilos.mockResolvedValue([{ ...HEALTHY[0], reachable: false, failure: 'FileNotFoundError' }, HEALTHY[1]])
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Reads are still being served, from the last sync/)).toBeInTheDocument()
    expect(screen.queryByText(/cannot be read/i)).not.toBeInTheDocument()
  })

  it('does not say that when nothing has stopped', async () => {
    // THE CONTROL. A notice rendered unconditionally would pass the
    // test above and fail this one.
    render(<Silos onSessionExpired={vi.fn()} />)
    await screen.findByRole('heading', { name: /published to gold/i })

    expect(screen.queryByText(/Reads are still being served/)).not.toBeInTheDocument()
  })

  it('says when a sync CANNOT fix a type that was never published', async () => {
    // Both facts were already on this screen in different sections.
    // Apart, the first one's advice is "run a sync"; together that is
    // advice nobody can take.
    getSilos.mockResolvedValue([HEALTHY[0], { ...HEALTHY[1], reachable: false, failure: 'FileNotFoundError' }])
    getDataFreshness.mockResolvedValue({
      source: 'gold',
      last_synced_at: null,
      published_at: { Customer: new Date().toISOString() },
    })
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/a sync cannot fix them yet/i)).toBeInTheDocument()
    expect(screen.getByText(/Ticket has never been published AND its source is not answering/)).toBeInTheDocument()
  })

  it("does not say that when the unpublished type's source is answering", async () => {
    // THE CONTROL FOR THE TEST ABOVE. This one genuinely IS a sync
    // away from working.
    getDataFreshness.mockResolvedValue({
      source: 'gold',
      last_synced_at: null,
      published_at: { Customer: new Date().toISOString() },
    })
    render(<Silos onSessionExpired={vi.fn()} />)

    expect(await screen.findByText(/Reads of Ticket will fail/)).toBeInTheDocument()
    expect(screen.queryByText(/a sync cannot fix them yet/i)).not.toBeInTheDocument()
  })
})
