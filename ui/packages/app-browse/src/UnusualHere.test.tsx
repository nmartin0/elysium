import { describe, expect, it, vi, beforeEach } from 'vitest'
import { render, renderHook, screen, waitFor } from '@testing-library/react'

vi.mock('@elysium/shell-api/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@elysium/shell-api/api')>()
  return { ...actual, getUnusualFor: vi.fn() }
})

import { getUnusualFor } from '@elysium/shell-api/api'
import { UnusualTag, useUnusualFor } from './UnusualHere'

const mocked = vi.mocked(getUnusualFor)
const VALUE = { field: 'amount', value: 300, reason: 'amount 300 is far above the usual 50.', decision: null }

beforeEach(() => {
  vi.clearAllMocks()
})

describe('an unusual value, marked on the row (R51)', () => {
  it('one word on the row, the reasons on hover', () => {
    render(<UnusualTag values={[VALUE, { ...VALUE, field: 'fee', reason: 'fee 9 is far below.' }]} />)

    const tag = screen.getByText('unusual')
    expect(tag.closest('[title]')?.getAttribute('title')).toBe(
      'amount 300 is far above the usual 50.\nfee 9 is far below.',
    )
  })

  it('nothing at all for a row with nothing unusual', () => {
    const { container } = render(
      <>
        <UnusualTag values={undefined} />
        <UnusualTag values={[]} />
      </>,
    )

    expect(container.textContent).toBe('')
  })
})

describe('asking which of the rows shown are unusual', () => {
  it('asks once for the ids on the page and answers by id', async () => {
    mocked.mockResolvedValue({ t1: [VALUE] })
    const { result } = renderHook(() => useUnusualFor('Transaction', ['t1', 't2']))

    await waitFor(() => expect(result.current).toEqual({ t1: [VALUE] }))
    expect(mocked).toHaveBeenCalledWith('Transaction', ['t1', 't2'])
  })

  it('the last page answer is not shown against this one while it is asked', async () => {
    // THE CONTROL: rows t1 were answered; t9's question is still out.
    mocked.mockResolvedValueOnce({ t1: [VALUE] })
    mocked.mockImplementationOnce(() => new Promise(() => {}))
    const { result, rerender } = renderHook(({ ids }) => useUnusualFor('Transaction', ids), {
      initialProps: { ids: ['t1'] },
    })
    await waitFor(() => expect(result.current).toEqual({ t1: [VALUE] }))
    rerender({ ids: ['t9'] })

    expect(mocked).toHaveBeenCalledTimes(2)
    expect(result.current).toEqual({})
  })

  it('a failed ask marks nothing, and no type asks nothing', async () => {
    mocked.mockRejectedValue(new Error('down'))
    const { result } = renderHook(() => useUnusualFor('Transaction', ['t1']))
    await waitFor(() => expect(mocked).toHaveBeenCalled())
    expect(result.current).toEqual({})

    mocked.mockClear()
    renderHook(() => useUnusualFor(null, ['t1']))
    expect(mocked).not.toHaveBeenCalled()
  })
})
