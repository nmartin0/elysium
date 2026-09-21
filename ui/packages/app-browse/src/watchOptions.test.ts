/**
 * Which actions and roles the Watch dialog offers.
 *
 * THE SAME RULES THE SERVER ENFORCES, applied early -- so the dialog
 * offers only what will be accepted rather than offering everything
 * and showing a refusal afterwards.
 */
import { describe, expect, it } from 'vitest'

import { actionsFor, rolesFor, type VisibleAction } from './watchOptions'

function action(overrides: Partial<VisibleAction> = {}): VisibleAction {
  return {
    executable: true,
    automatable: true,
    parameters: {
      transaction_ids: { type: 'object_reference_list', object_type: 'Transaction' },
      new_category: { type: 'string', display_name: 'New category' },
    },
    ...overrides,
  }
}

describe('actionsFor', () => {
  it('offers an action that fits', () => {
    const [choice] = actionsFor({ Recategorise: action() }, 'Transaction')

    expect(choice?.name).toBe('Recategorise')
    expect(choice?.targets).toEqual(['transaction_ids'])
  })

  it('separates the matched parameter from the others', () => {
    /** THE MATCHES FILL THE TARGET; the person fills the rest once. */
    const [choice] = actionsFor({ Recategorise: action() }, 'Transaction')

    expect(choice?.others.map(([name]) => name)).toEqual(['new_category'])
  })

  it('leaves out one the person cannot run', () => {
    /** A TRIGGER GRANTS NOTHING ITS OWNER LACKS. */
    expect(actionsFor({ R: action({ executable: false }) }, 'Transaction')).toEqual([])
  })

  it('leaves out one that refuses automation', () => {
    expect(actionsFor({ R: action({ automatable: false }) }, 'Transaction')).toEqual([])
  })

  it('leaves out one with no parameter for this type', () => {
    /** NOTHING TO RECEIVE WHAT THE VIEW MATCHED. */
    expect(actionsFor({ R: action() }, 'Customer')).toEqual([])
  })

  it('does not count a string parameter as a target', () => {
    const onlyString = action({ parameters: { note: { type: 'string' } } })

    expect(actionsFor({ R: onlyString }, 'Transaction')).toEqual([])
  })
})

describe('rolesFor', () => {
  it('offers every role to somebody who can see them all', () => {
    /** manage:users holders already see every role, through /config. */
    expect(rolesFor('analyst', ['reviewer', 'analyst'])).toEqual(['analyst', 'reviewer'])
  })

  it('offers only their own role to anybody else', () => {
    /** /config REFUSED THEM, which is the rule working. */
    expect(rolesFor('analyst', null)).toEqual(['analyst'])
  })

  it('offers nothing to somebody with no role', () => {
    expect(rolesFor(null, null)).toEqual([])
  })
})
