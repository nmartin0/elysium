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

describe('the shell is viewport-locked', () => {
  /**
   * These read the stylesheet, which is the only way to check a
   * layout jsdom does not compute. They exist because the fix for
   * this was reported as landed while the rule was not in the file at
   * all -- the commit had never reached the remote, and nothing
   * noticed.
   */

  it('locks the document so only the regions inside scroll', () => {
    expect(CSS).toMatch(/html,\s*\n\s*body,\s*\n\s*#root\s*\{[^}]*overflow:\s*hidden/)
  })

  it('gives the shell a DEFINITE height, not a minimum', () => {
    /**
     * THE bug. A min-height lets a track be pushed open by its
     * content, so the children's overflow:auto never engages -- the
     * content grows the layout past the viewport and the whole page
     * scrolls, chrome and all.
     */
    const app = /\.app \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(app).toMatch(/height:\s*100dvh/)
    expect(app).not.toMatch(/min-height/)
  })

  it('gives the sidebar its own scroll', () => {
    // Without it the shell's overflow:hidden clips the nav, and only
    // the first app shows.
    const sidebar = /\.app__sidebar \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(sidebar).toMatch(/overflow-y:\s*auto/)
  })

  it('leaves a sub-app without a workspace some padding', () => {
    // Zeroing it unconditionally for Browse's flush panels stripped
    // every other sub-app's breathing room.
    const main = /\.app__content main \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(main).toMatch(/padding:\s*var\(--space-loose\)/)
  })
})
