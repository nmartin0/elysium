/**
 * Row density, the reader's preference (DEV_UI 9.3).
 *
 * Three, because the design measured three: compact ~30px "for the
 * person scanning two hundred rows a shift", middle ~38px by default
 * "because the owner's first criterion is eye comfort", roomy ~48px for
 * touch. The heights live in tokens.css; this is only the vocabulary.
 */

export type Density = 'compact' | 'middle' | 'roomy'

export const DENSITIES: readonly { value: Density; label: string }[] = [
  { value: 'compact', label: 'Compact' },
  { value: 'middle', label: 'Middle' },
  { value: 'roomy', label: 'Roomy' },
]

/** A stored value is a Density only if it is one of the three -- a
 *  preference written by an older build must not set a height that
 *  does not exist. */
export function isDensity(value: unknown): value is Density {
  return DENSITIES.some((density) => density.value === value)
}
