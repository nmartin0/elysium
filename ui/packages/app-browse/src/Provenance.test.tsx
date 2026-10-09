import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const getObjectProvenance = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getObjectProvenance: () => getObjectProvenance() }
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

const show = (answer: unknown) => {
  getObjectProvenance.mockResolvedValue(answer)
  return render(<Provenance objectType="Customer" objectId="c1" />)
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
