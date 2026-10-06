import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'

/**
 * THE MOCK SHAPE IS NOT A DETAIL, and getting it wrong cost eleven
 * failing tests and most of a session.
 *
 * `vi.mock` is hoisted above static imports, so a component imported
 * with `import X from './X'` binds the REAL module. Silos.test.tsx --
 * the other panel built on `useFetchOnce` -- shows the shape that
 * works: bare `vi.fn()`s declared first, a factory returning arrows
 * that call them, and the component pulled in with a top-level
 * `await import()` AFTER the mock is registered.
 *
 * `vi.resetAllMocks()` in a beforeEach also strips the implementation,
 * so the fetcher returned undefined, `useFetchOnce` called `.then()`
 * on it, and the effect threw -- which is why the body was empty
 * rather than showing a spinner. There is no beforeEach here; each
 * test sets what it needs.
 */
const getMergeProposals = vi.fn()
const decideMergeProposal = vi.fn()

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return {
    ...actual,
    getMergeProposals: () => getMergeProposals(),
    decideMergeProposal: (id: string, decision: string, note?: string) => decideMergeProposal(id, decision, note),
  }
})

const { default: IdentityPanel } = await import('./IdentityPanel')

/**
 * A proposal where `email` was compared but may NOT be read by this
 * caller -- the case the whole feature exists for. Note what the
 * server sent: the email entry has a verdict and NO `left`/`right`
 * keys at all, because a withheld value is absent rather than null.
 */
const MASKED = {
  proposal_id: 'p1',
  object_type: 'Customer',
  left_id: 'cust_001',
  right_id: 'cust_002',
  proposed_at: '2026-10-01T09:00:00Z',
  decision: 'pending',
  pattern: 'agree,agree,differ',
  fields: [
    { field: 'name', verdict: 'agree', left: 'Ada Okafor', right: 'Ada Okafor' },
    { field: 'region', verdict: 'agree', left: 'us-east', right: 'us-east' },
    { field: 'email', verdict: 'differ' },
  ],
  withheld: ['email'],
}

const show = (proposals: unknown[]) => {
  getMergeProposals.mockResolvedValue(proposals)
  decideMergeProposal.mockResolvedValue(undefined)
  return render(<IdentityPanel onSessionExpired={vi.fn()} />)
}

describe('what the reviewer is shown', () => {
  it('lists a proposed pair', async () => {
    show([MASKED])

    const heading = await screen.findByRole('heading', { level: 3 })
    expect(heading.textContent).toContain('cust_001 and cust_002')
  })

  it('shows the agreement pattern, which is what they decide on', async () => {
    show([MASKED])

    expect(await screen.findByText('agree,agree,differ')).toBeTruthy()
  })

  it('gives every compared field a verdict, including the withheld one', async () => {
    /** Withholding the value must not withhold the judgement. "These
     *  two emails differ" tells a reviewer what they need and nothing
     *  about either address. */
    show([MASKED])

    await screen.findByText('email')
    expect(screen.getAllByText('agree').length).toBeGreaterThanOrEqual(2)
    expect(screen.getByText('differ')).toBeTruthy()
  })
})

describe('a withheld value renders as nothing at all', () => {
  it('no placeholder, no dash, no asterisks', async () => {
    /** THE TEST THIS SCREEN EXISTS TO PASS. A masked value was never
     *  sent, so there is nothing to represent -- and representing it
     *  would imply there is a value behind the mask for this reviewer
     *  to want. */
    const { container } = show([MASKED])

    await screen.findByText('email')
    const row = [...container.querySelectorAll('tr')].find((candidate) => candidate.textContent?.includes('email'))
    const cells = [...(row?.querySelectorAll('td') ?? [])]

    expect(cells[2]?.textContent).toBe('')
    expect(cells[3]?.textContent).toBe('')
  })

  it('names the withheld fields, so nobody thinks they saw everything', async () => {
    show([MASKED])

    expect(await screen.findByText(/you may not read/)).toBeTruthy()
  })

  it('says nothing about withheld fields when there are none', async () => {
    show([{ ...MASKED, withheld: [] }])

    await screen.findByText('email')
    expect(screen.queryByText(/you may not read/)).toBeNull()
  })
})

describe('the score is never shown', () => {
  it('because the decision is made on the pattern, not the number', async () => {
    /** A score invites deference to the matcher, which is the thing a
     *  human review exists to prevent. The route sends none; this
     *  checks the screen invents none. */
    const { container } = show([MASKED])

    await screen.findByText('agree,agree,differ')

    expect(container.textContent).not.toMatch(/0\.\d+/)
    expect(container.textContent?.toLowerCase()).not.toContain('score')
  })
})

describe('deciding', () => {
  it('records "same entity" as an approval', async () => {
    show([MASKED])

    fireEvent.click(await screen.findByRole('button', { name: 'Same entity' }))

    await waitFor(() => expect(decideMergeProposal).toHaveBeenCalledWith('p1', 'approved', undefined))
  })

  it('records "not the same" as a rejection', async () => {
    show([MASKED])

    fireEvent.click(await screen.findByRole('button', { name: 'Not the same' }))

    await waitFor(() => expect(decideMergeProposal).toHaveBeenCalledWith('p1', 'rejected', undefined))
  })

  it('shows a refusal rather than hiding the buttons', async () => {
    /** A reviewer with read but not write can work the queue and will
     *  be refused at the decision. Hiding the buttons would leave them
     *  looking at a list that does nothing, with no way to learn
     *  why. */
    getMergeProposals.mockResolvedValue([MASKED])
    decideMergeProposal.mockRejectedValue(new Error('Deciding a Customer merge needs write:Customer'))
    render(<IdentityPanel onSessionExpired={vi.fn()} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Same entity' }))

    expect(await screen.findByText(/needs write:Customer/)).toBeTruthy()
  })

  it('offers no buttons on a proposal already decided', async () => {
    show([{ ...MASKED, decision: 'approved', decided_by: 'carol' }])

    await screen.findByText(/Decided by carol/)
    expect(screen.queryByRole('button', { name: 'Same entity' })).toBeNull()
  })
})

describe('an empty queue', () => {
  it('says so rather than showing a blank panel', async () => {
    show([])

    expect(await screen.findByText('No proposed merges.')).toBeTruthy()
  })
})
