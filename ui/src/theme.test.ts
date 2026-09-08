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
    // On .app-frame now: the header sits above the columns, so the
    // outermost element is what the viewport lock belongs to.
    /**
     * THE bug. A min-height lets a track be pushed open by its
     * content, so the children's overflow:auto never engages -- the
     * content grows the layout past the viewport and the whole page
     * scrolls, chrome and all.
     */
    const app = /\.app-frame \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

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

describe('the stylesheet has one rule per selector', () => {
  it('defines no selector twice', () => {
    /**
     * Appending a second block instead of editing the first is how
     * two real bugs got in: a rule commented "not sticky" that never
     * removed `position: sticky`, and one claiming to fix the
     * workspace layout while `align-items: start` stayed in force
     * above it -- which sized each pane to its content, so neither
     * could scroll.
     *
     * The later block wins on the properties it names and silently
     * leaves the rest, which makes a comment describe something the
     * CSS does not do.
     */
    const selectors = [...CSS.matchAll(/^(\.[a-z_-][a-z_ -]*)\{/gm)]
      .map((match) => match[1]?.trim())
    const seen = new Set<string>()
    const duplicated = selectors.filter((selector) => {
      if (selector === undefined) return false
      if (seen.has(selector)) return true
      seen.add(selector)
      return false
    })

    expect(duplicated).toEqual([])
  })

  it('lets the workspace panes fill the shell so they can scroll', () => {
    // align-items: start sizes each pane to its content. Nothing
    // constrains them, so overflow-y: auto never engages.
    const workspace = /\.workspace \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(workspace).toMatch(/align-items:\s*stretch/)
    expect(workspace).toMatch(/height:\s*100%/)
  })
})

describe('chrome is continuous', () => {
  it('draws no border straight under the header', () => {
    /**
     * A full-width border under the header cut a grey line through the
     * chrome exactly where the header meets the rail -- two surfaces
     * of the same colour with a seam between them.
     *
     * The header and rail are one piece of furniture wrapping the
     * content. The separation that matters is chrome against CONTENT,
     * so the rule starts where the rail ends.
     */
    const header = /\.app__header \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(header).not.toMatch(/border-bottom/)
  })

  it('separates the header from the canvas only', () => {
    const seam = /\.app__header::after \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(seam).toMatch(/left:\s*var\(--sidebar-rail\)/)
  })

  it('draws no box around the collapse toggle', () => {
    /**
     * It is chrome ON chrome. A border around it draws the same kind
     * of seam the header border did -- a line through a continuous
     * surface.
     *
     * This test exists because the fix "landed" while the border was
     * still there: the replacement matched no text, and I reported it
     * as done. Checking the claim is what caught it.
     */
    const toggle = /\.app__sidebar-toggle \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(toggle).toMatch(/border:\s*none/)
  })
})
