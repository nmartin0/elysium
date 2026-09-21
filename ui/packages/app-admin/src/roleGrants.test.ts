/**
 * Grants arranged for reading, and a change as its difference.
 *
 * AN APPROVER READS A DIFFERENCE, NOT TWO LISTS: comparing dozens of
 * grants by eye is how the one line that matters gets missed.
 */
import { describe, expect, it } from 'vitest'

import { groupGrants, summariseChange } from './roleGrants'

describe('groupGrants', () => {
  const groups = groupGrants([
    'manage:users',
    'manage:roles',
    'discover:action_types',
    'execute:Rename',
    'tool:search',
    'read:Customer',
    'read:Customer.email',
    'read:Account',
  ])

  it('puts administration first', () => {
    /** THOSE CHANGE WHO MAY DO WHAT, so they are seen first. */
    expect(groups[0]?.title).toBe('Administration')
    expect(groups[0]?.grants).toContain('manage:roles')
  })

  it('keeps discover:action_types with administration, not with a type', () => {
    expect(groups[0]?.grants).toContain('discover:action_types')
  })

  it('gathers a type with its fields', () => {
    const customer = groups.find((group) => group.title === 'Customer')

    expect(customer?.grants).toEqual(['read:Customer', 'read:Customer.email'])
  })

  it('orders types by name', () => {
    const types = groups.slice(3).map((group) => group.title)

    expect(types).toEqual(['Account', 'Customer'])
  })
})

describe('summariseChange', () => {
  it('names only what is added and removed', () => {
    const summary = summariseChange(['read:A', 'read:B'], ['read:B', 'read:C'])

    expect(summary).toEqual({ kind: 'edit', added: ['read:C'], removed: ['read:A'] })
  })

  it('shows unchanged grants nowhere', () => {
    /** THE GRANT BOTH SIDES SHARE is exactly what an approver should
     *  not have to read past. */
    const summary = summariseChange(['read:B'], ['read:B', 'read:C'])

    expect([...summary.added, ...summary.removed]).not.toContain('read:B')
  })

  it('reads a missing before as a new role', () => {
    expect(summariseChange(null, ['read:A']).kind).toBe('create')
  })

  it('reads a missing after as a deletion, removing everything', () => {
    expect(summariseChange(['read:A'], null)).toEqual({
      kind: 'delete',
      added: [],
      removed: ['read:A'],
    })
  })
})
