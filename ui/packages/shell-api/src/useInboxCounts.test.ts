import { describe, expect, it } from 'vitest'

import { totalWaiting } from './useInboxCounts'

describe('totalWaiting', () => {
  it('adds the four queues', () => {
    expect(totalWaiting({ approvals: 2, notifications: 3, identity: 1, enrichment: 4 })).toBe(10)
  })

  it('reads a server that predates the enrichment count as none there, not NaN', () => {
    const older = { approvals: 2, notifications: 3, identity: 1 } as unknown as Parameters<typeof totalWaiting>[0]
    expect(totalWaiting(older)).toBe(6)
  })

  it('is nothing while the counts are unknown -- absent, not an error', () => {
    expect(totalWaiting(null)).toBe(0)
  })
})

describe('useInboxCounts re-reads when told (16 October)', () => {
  it('reads again the moment the server says the inbox changed, not a minute later', async () => {
    const { renderHook, waitFor } = await import('@testing-library/react')
    const { vi } = await import('vitest')
    const api = await import('./api')
    const live = await import('./liveUpdates')

    let tell: () => void = () => {}
    vi.spyOn(live, 'subscribeToInbox').mockImplementation((listener) => {
      tell = listener
      return () => {}
    })
    const read = vi
      .spyOn(api, 'getInboxCounts')
      .mockResolvedValueOnce({ approvals: 0, notifications: 0, identity: 0, enrichment: 0 })
      .mockResolvedValueOnce({ approvals: 0, notifications: 1, identity: 0, enrichment: 0 })
    const { useInboxCounts } = await import('./useInboxCounts')

    const { result } = renderHook(() => useInboxCounts('/'))
    await waitFor(() => expect(result.current?.notifications).toBe(0))

    tell()

    await waitFor(() => expect(result.current?.notifications).toBe(1))
    expect(read).toHaveBeenCalledTimes(2)
    vi.restoreAllMocks()
  })
})
