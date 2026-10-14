import { describe, expect, it } from 'vitest'

import { DENSITIES, isDensity } from './density'

describe('density', () => {
  it('is three, in order of row height', () => {
    expect(DENSITIES.map((density) => density.value)).toEqual(['compact', 'middle', 'roomy'])
  })

  it('refuses a stored value that is not one of them', () => {
    // A preference from an older build must not set a height that
    // does not exist.
    expect(isDensity('middle')).toBe(true)
    expect(isDensity('spacious')).toBe(false)
    expect(isDensity(null)).toBe(false)
  })
})
