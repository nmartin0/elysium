import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const getObjectProvenance = vi.fn()
const getObjectConflicts = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getObjectProvenance: () => getObjectProvenance(),
    getObjectConflicts: () => getObjectConflicts(),
  }
})

const { default: Provenance } = await import('./Provenance')

/**
 * The fixture matches ObjectProvenanceResponse -- silo, source_table,
 * row_hash, bronze_snapshot_id -- rather than a shape I assumed.
 */
const LINEAGE = {
  silo: 'primary_sql',
  source_table: 'customers',
  row_hash: 'a1b2c3',
  bronze_snapshot_id: 'snap-42',
}

const show = (answer: unknown, conflicts: unknown = []) => {
  getObjectProvenance.mockResolvedValue(answer)
  getObjectConflicts.mockResolvedValue(conflicts)
  return render(<Provenance objectType="Customer" objectId="c1" />)
}

/** As the route serves it: the field, both sources, and the values
 *  only when the caller may read the field. */
const NAME_CONFLICT = {
  kind: 'property',
  field: 'name',
  chosen: 'Ada Okafor',
  chosen_source: 'crm',
  losing: 'Ada',
  losing_source: 'primary',
  recorded_at: '2026-10-11T00:00:00+00:00',
  readable: true,
}

describe('where a row came from', () => {
  it('names the source, the table and the snapshot it came from', async () => {
    show(LINEAGE)

    expect(await screen.findByText('primary_sql')).toBeInTheDocument()
    expect(screen.getByText('customers')).toBeInTheDocument()
    expect(screen.getByText('snap-42')).toBeInTheDocument()
  })

  it('leaves out a field the deployment does not record', async () => {
    /** A live-read deployment has no bronze snapshot. A row labelled
     *  with an empty value reads as a fault; omitting it reads as the
     *  fact it is. */
    const { container } = show({ ...LINEAGE, bronze_snapshot_id: null })

    await screen.findByText('primary_sql')
    expect(container.textContent).not.toContain('Bronze snapshot')
  })
})

describe('a reader who may not ask', () => {
  /**
   * The route is gated on manage:users, because the silo and
   * source-table names identify the customer's own systems and /silos
   * already treats those as admin-only. So a refusal here is the
   * ORDINARY case.
   */

  it('renders nothing at all when the request is refused', async () => {
    getObjectProvenance.mockRejectedValue(new Error('403'))
    const { container } = render(<Provenance objectType="Customer" objectId="c1" />)

    await waitFor(() => expect(getObjectProvenance).toHaveBeenCalled())

    expect(container.innerHTML).toBe('')
  })

  it('gives no hint that there was something to withhold', async () => {
    /** The opposite of what the field table does, deliberately. A
     *  withheld FIELD says "Not permitted", because the reader can see
     *  the object. This panel is about the DEPLOYMENT's plumbing, and
     *  somebody who may not administer it gains nothing from learning
     *  that a provenance panel exists. */
    getObjectProvenance.mockRejectedValue(new Error('403'))
    const { container } = render(<Provenance objectType="Customer" objectId="c1" />)

    await waitFor(() => expect(getObjectProvenance).toHaveBeenCalled())

    expect(container.textContent).not.toMatch(/permitted|denied|forbidden/i)
    expect(container.textContent).not.toMatch(/where this came from/i)
  })

  it('renders nothing when there is no row to describe', async () => {
    const { container } = show(null)

    await waitFor(() => expect(getObjectProvenance).toHaveBeenCalled())

    expect(container.innerHTML).toBe('')
  })

  it('renders nothing when every field is absent', async () => {
    /** A live-read deployment answers with the shape and no values. */
    const { container } = show({})

    await waitFor(() => expect(getObjectProvenance).toHaveBeenCalled())

    expect(container.innerHTML).toBe('')
  })
})

describe('where the sources disagreed', () => {
  /**
   * `core/mirror/survivorship.py` states the promise: "deleting losing
   * values destroys trust. A person asking why the golden record says
   * Leeds needs to see that the CRM said Hull and was outranked --
   * otherwise the answer is an assertion." The losing values have been
   * written since GOLD-6 and nothing could read them back.
   */
  it('shows the value that won and the one it outranked', async () => {
    show(LINEAGE, [NAME_CONFLICT])

    expect(await screen.findByText(/where the sources disagreed/i)).toBeInTheDocument()
    expect(screen.getByText('Ada Okafor')).toBeInTheDocument()
    expect(screen.getByText('Ada')).toBeInTheDocument()
  })

  it('names which source each value came from', async () => {
    // THE PER-FIELD HALF, which nothing else in the system has: the
    // lineage above says one silo for the whole object however many
    // it was fused from.
    show(LINEAGE, [NAME_CONFLICT])

    expect(await screen.findByText('from crm')).toBeInTheDocument()
    expect(screen.getByText('from primary')).toBeInTheDocument()
  })

  it('says whose value held when these two disagreed before (R60)', async () => {
    show(LINEAGE, [
      { ...NAME_CONFLICT, track_record: { source: 'crm', about_percent: 80 } },
      { ...NAME_CONFLICT, field: 'email', recorded_at: '2026-10-11T00:00:01+00:00' },
    ])

    expect(await screen.findByText(/when these two disagreed before/i)).toBeInTheDocument()
    expect(screen.getByText("crm's value held about 80% of the time")).toBeInTheDocument()
    // A row without enough history says so rather than leaving a blank.
    expect(screen.getByText('not enough history')).toBeInTheDocument()
  })

  it('says which sources the majority sides with, and names copies (R60)', async () => {
    show(LINEAGE, [
      {
        ...NAME_CONFLICT,
        vote: { majority: ['erp', 'web'], sources: ['billing', 'crm', 'erp', 'web'], copies: [['billing', 'crm']] },
        agreement: { crm: 60 },
      },
    ])

    expect(await screen.findByText(/most independent sources/i)).toBeInTheDocument()
    expect(screen.getByText(/agree with erp and web/)).toBeInTheDocument()
    expect(screen.getByText(/billing and crm look like copies, counted once/)).toBeInTheDocument()
    expect(screen.getByText(/crm sides with the majority about 60% of the time/)).toBeInTheDocument()
  })

  it('says a tie is a tie', async () => {
    show(LINEAGE, [{ ...NAME_CONFLICT, vote: { majority: [], sources: ['a', 'b', 'c'], copies: [] } }])

    expect(await screen.findByText(/no majority: a tie/)).toBeInTheDocument()
  })

  it('adds no vote column when no row has one', async () => {
    show(LINEAGE, [NAME_CONFLICT])

    await screen.findByText(/where the sources disagreed/i)
    expect(screen.queryByText(/most independent sources/i)).not.toBeInTheDocument()
  })

  it('adds no column when no row has a track record', async () => {
    show(LINEAGE, [NAME_CONFLICT])

    await screen.findByText(/where the sources disagreed/i)
    expect(screen.queryByText(/when these two disagreed before/i)).not.toBeInTheDocument()
  })

  it('says nothing at all when nothing disagreed', async () => {
    // THE CONTROL, and the reason there is no empty state: most
    // deployments declare no identity resolution and would otherwise
    // carry a reassurance on every object page about the absence of a
    // feature they do not use.
    show(LINEAGE, [])

    await screen.findByText(/where this came from/i)
    expect(screen.queryByText(/where the sources disagreed/i)).not.toBeInTheDocument()
  })

  it('shows a FILL as a fill, not a disagreement (R67a)', async () => {
    // The CRM was preferred and held nothing in `name`; billing's value
    // was served. Nothing was disputed, so the heading must not say so.
    show(LINEAGE, [{ ...NAME_CONFLICT, kind: 'filled', chosen_source: 'primary', losing: null, losing_source: 'crm' }])

    expect(await screen.findByText(/where a value came from another source/i)).toBeInTheDocument()
    expect(screen.getByText('empty in crm')).toBeInTheDocument()
    expect(screen.queryByText(/where the sources disagreed/i)).not.toBeInTheDocument()
  })

  it('shows a contested COMPARTMENT differently from a contested field', async () => {
    // A security conflict names no field, because what is contested is
    // the whole object -- which compartment it belongs to, and
    // therefore who may see it.
    show(LINEAGE, [{ ...NAME_CONFLICT, kind: 'security', field: null, chosen: 'us-west', losing: 'us-east' }])

    expect(await screen.findByText('Which compartment')).toBeInTheDocument()
  })

  it('withholds the values of a field the reader may not read', async () => {
    // THE VERDICT IS SAFE AND THE VALUES ARE NOT -- the rule
    // masked_comparison follows for a merge candidate. A reader can be
    // told two sources disagreed about an email without being shown
    // either address.
    show(LINEAGE, [
      // THE VALUES ARE IN THE FIXTURE ON PURPOSE, and the route would
      // never send them beside `readable: false`. A first version left
      // them out, which made this test unable to fail: with nothing to
      // leak, a component ignoring the flag entirely rendered the same
      // thing, and a control confirmed it. The component holds its own
      // half of the rule rather than trusting the server to have held
      // its half.
      {
        kind: 'property',
        field: 'email',
        chosen: 'ada@crm.example',
        chosen_source: 'crm',
        losing: 'ada@billing.example',
        losing_source: 'primary',
        recorded_at: '2026-10-11T00:00:00+00:00',
        readable: false,
      },
    ])

    expect(await screen.findByText('email')).toBeInTheDocument()
    expect(screen.getByText('from crm')).toBeInTheDocument()
    expect(screen.getByText(/may not read those fields/)).toBeInTheDocument()
    expect(screen.queryByText('ada@crm.example')).not.toBeInTheDocument()
    expect(screen.queryByText('ada@billing.example')).not.toBeInTheDocument()
  })

  it('does not say that when every value is readable', async () => {
    // THE CONTROL FOR THE TEST ABOVE. A note rendered unconditionally
    // would tell every reader that something was kept from them.
    show(LINEAGE, [NAME_CONFLICT])

    await screen.findByText('Ada Okafor')
    expect(screen.queryByText(/may not read those fields/)).not.toBeInTheDocument()
  })

  it('still shows them when there is no lineage to show', async () => {
    // Two tables, two questions. A live-read deployment has no lineage
    // at all, and making one conditional on the other would hide the
    // half that exists.
    show(null, [NAME_CONFLICT])

    expect(await screen.findByText('Ada Okafor')).toBeInTheDocument()
  })

  it('renders nothing when the route refuses', async () => {
    // Refused and unreachable are the same nothing, for the reason
    // the lineage fetch gives: distinguishing them would tell a reader
    // without the grant that the grant exists.
    getObjectProvenance.mockResolvedValue(LINEAGE)
    getObjectConflicts.mockRejectedValue(new Error('403'))
    render(<Provenance objectType="Customer" objectId="c1" />)

    await screen.findByText(/where this came from/i)
    expect(screen.queryByText(/where the sources disagreed/i)).not.toBeInTheDocument()
  })
})

describe('which source supplied each value (R38)', () => {
  it('names the source of every field of a fused object', async () => {
    show({ ...LINEAGE, field_sources: { name: 'primary', risk_score: 'risk_db' } })

    const heading = await screen.findByText('Which source supplied each value')
    const section = heading.closest('section') as HTMLElement
    expect(section).toHaveTextContent('risk_scorerisk_db')
    expect(section).toHaveTextContent('nameprimary')
  })

  it('calls the silo the PRIMARY one when fields came from several', async () => {
    show({ ...LINEAGE, field_sources: { risk_score: 'risk_db' } })

    expect(await screen.findByText('Primary silo')).toBeInTheDocument()
    expect(screen.queryByText('Silo')).not.toBeInTheDocument()
  })

  it('shows no list for a single-source object, where the silo is the answer', async () => {
    show({ ...LINEAGE, field_sources: null })

    expect(await screen.findByText('Silo')).toBeInTheDocument()
    expect(screen.queryByText('Which source supplied each value')).not.toBeInTheDocument()
  })
})
