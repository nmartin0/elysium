import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'

const getPublishedHistory = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getPublishedHistory: () => getPublishedHistory() }
})

const { default: PublishedHistory } = await import('./PublishedHistory')

/**
 * The fixture matches PublishedChangeResponse -- change, changed_at,
 * publication, values -- rather than a shape I assumed. A fixture that
 * does not match the API is a test that proves nothing about the API.
 */
const CHANGE = {
  change: 'update',
  changed_at: '2026-09-07T10:00:00Z',
  publication: 'gold-2026-09-07',
  values: { region: 'us-east', risk_score: 0.4 },
}

const props = { objectType: 'Customer', objectId: 'c1', onSessionExpired: vi.fn() }

const show = (changes: unknown[]) => {
  getPublishedHistory.mockResolvedValue(changes)
  return render(<PublishedHistory {...props} />)
}

describe('what changed at the source', () => {
  it('lists a recorded change with its timestamp', async () => {
    show([CHANGE])

    expect(await screen.findByText('2026-09-07T10:00:00Z')).toBeInTheDocument()
    expect(screen.getByText('update')).toBeInTheDocument()
  })

  it('names which fields moved, not what they became', async () => {
    /** A history table is read to find WHAT moved. A row of values makes
     *  that harder; opening the object shows them. */
    show([CHANGE])

    expect(await screen.findByText('region, risk_score')).toBeInTheDocument()
    expect(screen.queryByText('us-east')).not.toBeInTheDocument()
  })

  it('names the publication that carried it, when the lake records one', async () => {
    show([CHANGE])

    expect(await screen.findByText(/gold-2026-09-07/)).toBeInTheDocument()
  })

  it('says nothing about a publication when there is none', async () => {
    show([{ ...CHANGE, publication: null }])

    await screen.findByText('update')
    expect(screen.queryByText(/^in /)).not.toBeInTheDocument()
  })
})

describe('an empty list', () => {
  it('is a sentence, not an empty table', async () => {
    /** THREE ORDINARY CAUSES, and the panel does not guess which:
     *  nothing has changed since publication, the deployment reads live
     *  and publishes nothing, or the caller may not read this object --
     *  the route returns an empty list rather than a 403, so uniform
     *  denial is preserved. Saying "no changes" plainly is true in all
     *  three. */
    show([])

    expect(await screen.findByText(/Nothing recorded since this object was last published/)).toBeInTheDocument()
  })

  it('does not claim the object is unchanged in the source', async () => {
    /** It cannot know that. An empty response from a caller who may not
     *  read the object looks identical. */
    const { container } = show([])

    await screen.findByText(/Nothing recorded/)
    expect(container.textContent).not.toMatch(/never changed|unchanged/i)
  })
})

describe('fields the caller may not read', () => {
  it('says so rather than leaving the cell blank', async () => {
    /** An empty cell reads as a rendering fault. This is a deliberate
     *  disclosure boundary, and the edit history already words it this
     *  way. */
    show([{ ...CHANGE, values: {} }])

    expect(await screen.findByText('fields you cannot read')).toBeInTheDocument()
  })
})
