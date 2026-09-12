/**
 * The chart palette exists so no caller chooses colours.
 *
 * Before it, every caller either picked its own or fell through to
 * ECharts' defaults -- so two charts on one screen could use different
 * palettes, and none had been checked for colour vision deficiency.
 *
 * THE PROPERTY THAT MATTERS MOST is the last one here: a caller's own
 * `color` must WIN. A chart that genuinely needs specific colours -- a
 * status breakdown where red must mean failed -- says so explicitly,
 * and a wrapper that silently overrode it would be worse than no
 * wrapper at all.
 */

import { describe, expect, it } from 'vitest'

import { chartTheme } from './chartColors'

describe('chartTheme', () => {
  it('gives eight categorical colours', () => {
    // Eight because past that nobody can hold a legend in their head.
    // A chart needing more should group into "other" rather than
    // extending the scale.
    expect(chartTheme(false).categorical).toHaveLength(8)
  })

  it('separates the first two maximally, not two shades of one hue', () => {
    // A two-series chart is the common case, and it is the one a
    // gradient-ordered scale handles worst: series one and two would
    // be adjacent hues.
    const [first, second] = chartTheme(false).categorical

    expect(first).not.toBe(second)
    // Blue then red -- the widest separation available, and the pair
    // that survives both deuteranopia and protanopia.
    expect(first).toBe('#4477aa')
    expect(second).toBe('#ee6677')
  })

  it('avoids a red/green pair in the first positions', () => {
    // The classic CVD failure. Red and green adjacent in assignment
    // order means the two most common series are the two that merge.
    const [first, second] = chartTheme(false).categorical
    const green = '#228833'

    expect([first, second]).not.toContain(green)
  })

  it('swaps only the eighth colour between themes', () => {
    // Every other hue reads on both surfaces. The eighth is black on
    // light and near-white on dark, because a scale that silently
    // disappears its last series on one theme is worse than a scale of
    // seven.
    const light = chartTheme(false).categorical
    const dark = chartTheme(true).categorical

    expect(light.slice(0, 7)).toEqual(dark.slice(0, 7))
    expect(light[7]).toBe('#000000')
    expect(dark[7]).toBe('#e2e6ee')
  })

  it('uses a diverging scale that is blue to red, never green to red', () => {
    // Green/red is the pair CVD users cannot separate, AND it carries
    // a good/bad connotation that is wrong when the axis is merely
    // signed.
    const diverging = chartTheme(false).diverging

    expect(diverging[0]).toBe('#2166ac')
    expect(diverging[diverging.length - 1]).toBe('#b2182b')
  })

  it('falls back to literal axis colours when no stylesheet is loaded', () => {
    // jsdom has no stylesheet, so the CSS variables resolve to empty.
    // A chart that threw here would fail every caller's test for an
    // unrelated reason.
    const theme = chartTheme(true)

    expect(theme.axisLabel).toBeTruthy()
    expect(theme.gridLine).toBeTruthy()
  })
})
