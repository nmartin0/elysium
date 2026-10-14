import { describe, expect, it } from 'vitest'

import { totalWaiting } from './useInboxCounts'

describe('totalWaiting', () => {
  it('adds the three queues', () => {
    expect(totalWaiting({ approvals: 2, notifications: 3, identity: 1 })).toBe(6)
  })

  it('is nothing while the counts are unknown -- absent, not an error', () => {
    expect(totalWaiting(null)).toBe(0)
  })
})
