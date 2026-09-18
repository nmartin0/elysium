/**
 * chartColors.ts -- the colour work charts need and UI tokens cannot do.
 *
 * WHY THIS IS SEPARATE FROM tokens.css. The UI palette answers "what
 * role does this element play" -- chrome, surface, danger. A chart
 * answers a different question: "which of these eight things is this
 * one", or "how far along a magnitude is this". An accent token cannot
 * do that job, and stretching it to try produces charts where three
 * series are indistinguishable.
 *
 * BLUEPRINT DOES NOT PROVIDE THIS. Its intents are semantic -- success,
 * warning, danger -- and a categorical scale must NOT be semantic: the
 * fourth category is not "more dangerous" than the third. So this is
 * the one palette decision that does not conflict with the
 * Blueprint-first rule, because there is nothing of Blueprint's to
 * conflict with.
 *
 * CVD-SAFE BY CONSTRUCTION, NOT BY EYE. Deuteranopia and protanopia
 * together affect roughly 1 in 12 men, and the classic failure is a
 * red/green pair that reads as one colour. The categorical scale below
 * is Paul Tol's qualitative "bright" scheme, published specifically to
 * remain distinguishable under both -- chosen rather than invented
 * because "looks fine to me" is exactly the test that fails here.
 *
 * NEVER COLOUR ALONE. These scales make series distinguishable; they
 * do not make them identifiable. Every chart still needs direct
 * labels, a legend, or shape/pattern encoding -- the same rule the UI
 * applies to status colours.
 */

/**
 * Up to eight categories, in assignment order.
 *
 * Ordered so the FIRST FEW are maximally separated: a two-series chart
 * gets blue and red, not two blues. Charts needing more than eight
 * categories should group into "other" rather than extending this --
 * past eight, nobody can hold the legend in their head anyway.
 */
const CATEGORICAL = [
  '#4477aa', // blue
  '#ee6677', // red
  '#228833', // green
  '#ccbb44', // yellow
  '#66ccee', // cyan
  '#aa3377', // purple
  '#bbbbbb', // grey
  '#000000', // black -- replaced per theme below
] as const

/**
 * Magnitude, low to high. Monotonic in lightness, so it survives
 * greyscale printing and photocopying -- which an operational report
 * genuinely encounters.
 */
const SEQUENTIAL = ['#ffffe5', '#fff7bc', '#fee391', '#fec44f', '#fe9929', '#ec7014', '#cc4c02', '#8c2d04'] as const

/**
 * Above and below a baseline, with a neutral midpoint.
 *
 * Blue/red rather than green/red, deliberately: green/red is the pair
 * deuteranopes and protanopes cannot separate, and it is also the pair
 * carrying an unwanted good/bad connotation when the axis is merely
 * signed.
 */
const DIVERGING = ['#2166ac', '#4393c3', '#92c5de', '#d1e5f0', '#fddbc7', '#f4a582', '#d6604d', '#b2182b'] as const

export interface ChartTheme {
  categorical: readonly string[]
  sequential: readonly string[]
  diverging: readonly string[]
  /** Axis labels. The secondary text token's value per theme. */
  axisLabel: string
  /** Gridlines. The subtle border token's value per theme. */
  gridLine: string
}

/**
 * The eighth categorical entry is black on light and near-white on
 * dark. Every other hue reads on both surfaces; that one does not, and
 * a scale that silently disappears its last series on one theme is
 * worse than a scale of seven.
 */
function categoricalFor(dark: boolean): readonly string[] {
  return [...CATEGORICAL.slice(0, 7), dark ? '#e2e6ee' : '#000000']
}

/**
 * Axis and gridline colours are read from the LIVE CSS custom
 * properties rather than duplicated here, so a token change moves the
 * charts with it. Falls back to a literal when the variable is absent
 * -- which happens in tests, where no stylesheet is loaded, and a
 * chart that throws in jsdom would make every caller's test fail for
 * an unrelated reason.
 */
function cssVar(name: string, fallback: string): string {
  if (typeof getComputedStyle !== 'function' || typeof document === 'undefined') {
    return fallback
  }
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value === '' ? fallback : value
}

export function chartTheme(dark: boolean): ChartTheme {
  return {
    categorical: categoricalFor(dark),
    sequential: SEQUENTIAL,
    diverging: DIVERGING,
    axisLabel: cssVar('--text-secondary', dark ? '#a2abbb' : '#5f6b7c'),
    gridLine: cssVar('--border-subtle', dark ? '#2d3543' : '#d3d8de'),
  }
}
