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
