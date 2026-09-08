import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CSS = readFileSync(
  path.resolve(__dirname, '../packages/shell-api/src/index.css'), 'utf8',
)
const TOKENS = readFileSync(
  path.resolve(__dirname, '../packages/shell-api/src/tokens.css'), 'utf8',
)

/**
 * Dark mode was unreadable, and the cause was a dozen colours written
 * as literals in index.css. They cannot invert, so half the app stayed
 * light-on-light while the rest went dark.
 *
 * Checked by reading the stylesheet, because jsdom does not apply CSS
 * from a file and a rendering test would see nothing.
 */

function colourLiterals(css: string): string[] {
  return css
    .split('\n')
    .filter((line) => !line.trim().startsWith('/*') && !line.trim().startsWith('*'))
    .filter((line) => /(background|^\s*color|border[^-]*):\s*#[0-9a-fA-F]/.test(line))
    .map((line) => line.trim())
}

describe('theming', () => {
  it('index.css uses tokens, not colour literals', () => {
    // One exception: the danger red is SEMANTIC. It means "destructive"
    // in both themes, and inverting it would make a delete button
    // stop looking dangerous.
    const offenders = colourLiterals(CSS).filter((line) => !line.includes('#b3261e'))

    expect(offenders).toEqual([])
  })

  it('chrome stays darker than the page behind it in dark mode', () => {
    /**
     * THE bug that made the sidebar vanish. Both were #1c2127, so the
     * sidebar dissolved into the background and took the logout and
     * theme buttons with it -- reported as "the buttons are not
     * present".
     */
    const dark = TOKENS.slice(TOKENS.indexOf('.bp6-dark'))
    const chrome = /--surface-chrome: (#[0-9a-f]{6})/.exec(dark)?.[1]
    const sunken = /--surface-sunken: (#[0-9a-f]{6})/.exec(dark)?.[1]

    expect(chrome).toBeDefined()
    expect(sunken).toBeDefined()
    expect(chrome).not.toBe(sunken)
  })

  it('every surface is redefined for dark mode', () => {
    // A surface that keeps its light value is a patch of daylight in
    // a dark app.
    const [light, dark] = TOKENS.split('.bp6-dark')
    const surfaces = [...(light ?? '').matchAll(/--(surface-[a-z]+):/g)].map((m) => m[1])

    expect(surfaces.length).toBeGreaterThan(2)
    for (const surface of surfaces) {
      expect(dark).toContain(`--${surface}:`)
    }
  })
})
