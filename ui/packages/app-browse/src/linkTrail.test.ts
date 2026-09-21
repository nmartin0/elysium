/**
 * The trail exists only while the filter it describes is untouched.
 *
 * THE TRAIL DESCRIBES THE CURRENT FILTER, NOT HISTORY. Change that
 * filter and "Ada Okafor's transactions" would be a lie about what is
 * on screen.
 */
import { describe, expect, it } from 'vitest'

import { activeTrail } from './linkTrail'

const ORIGIN = { type: 'Customer', id: 'cust_001', field: 'customer_id' }
const LINK_FILTER = { field: 'customer_id', values: ['cust_001'], mode: 'keep' as const }

describe('activeTrail', () => {
  it('shows while the link filter is exactly as it arrived', () => {
    expect(activeTrail(ORIGIN, [LINK_FILTER])).toEqual(ORIGIN)
  })

  it('survives other filters being added beside it', () => {
    /** NARROWING IS STILL "Ada Okafor's transactions" -- just fewer. */
    const other = { field: 'category', values: ['food'], mode: 'keep' as const }

    expect(activeTrail(ORIGIN, [LINK_FILTER, other])).toEqual(ORIGIN)
  })

  it('goes when the filter is removed', () => {
    expect(activeTrail(ORIGIN, [])).toBeNull()
  })

  it('goes when a second value is added', () => {
    /** TWO CUSTOMERS' TRANSACTIONS are not Ada Okafor's. */
    const widened = { ...LINK_FILTER, values: ['cust_001', 'cust_002'] }

    expect(activeTrail(ORIGIN, [widened])).toBeNull()
  })

  it('goes when the filter is flipped to exclude', () => {
    /** EVERYONE BUT HER is the opposite of the trail. */
    expect(activeTrail(ORIGIN, [{ ...LINK_FILTER, mode: 'exclude' }])).toBeNull()
  })

  it('goes when it names a different id', () => {
    expect(activeTrail(ORIGIN, [{ ...LINK_FILTER, values: ['cust_002'] }])).toBeNull()
  })

  it('treats anything malformed as no trail', () => {
    /** THE URL IS EDITABLE BY HAND, and a trail built from a guess is
     *  worse than none. */
    expect(activeTrail(null, [LINK_FILTER])).toBeNull()
    expect(activeTrail({ type: 'Customer' }, [LINK_FILTER])).toBeNull()
    expect(activeTrail('Customer/cust_001', [LINK_FILTER])).toBeNull()
  })
})
