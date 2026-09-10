import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CSS = readFileSync(path.resolve(__dirname, '../packages/shell-api/src/index.css'), 'utf8')
const TOKENS = readFileSync(path.resolve(__dirname, '../packages/shell-api/src/tokens.css'), 'utf8')

/**
 * Dark mode was unreadable, and the cause was a dozen colours written
 * as literals in index.css. They cannot invert, so half the app stayed
 * light-on-light while the rest went dark.
 *
 * Checked by reading the stylesheet, because jsdom does not apply CSS
 * from a file and a rendering test would see nothing.
 */

function colourLiterals(css: string): string[] {
  return (
    css
      .split('\n')
      .filter((line) => !line.trim().startsWith('/*') && !line.trim().startsWith('*'))
      // NAMED colours too, not just hex. An earlier version matched
      // only `#`, so seven `background: white` declarations passed
      // straight through and never inverted in dark mode.
      .filter((line) => /(background|^\s*color|border[^-]*):\s*(#[0-9a-fA-F]|white|black|rgb)/.test(line))
      .map((line) => line.trim())
  )
}

describe('theming', () => {
  it('index.css uses tokens, not colour literals', () => {
    // One exception: the danger red is SEMANTIC. It means "destructive"
    // in both themes, and inverting it would make a delete button
    // stop looking dangerous.
    /**
     * Two kinds of exception, both deliberate:
     *
     * - The danger red is SEMANTIC. It means "destructive" in both
     *   themes, and inverting it would make a delete button stop
     *   looking dangerous. The white on top of it goes with it.
     * - Translucent white overlays. rgba(255,255,255,alpha) on chrome
     *   is a LIGHTENING, not a colour: it works on any dark surface,
     *   in either theme, and a token would fix it to one.
     */
    const offenders = colourLiterals(CSS).filter(
      (line) => !line.includes('#b3261e') && !line.includes('#ffffff') && !/rgba\(255,\s*255,\s*255/.test(line),
    )

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
    const selectors = [...CSS.matchAll(/^(\.[a-z_-][a-z_ -]*)\{/gm)].map((match) => match[1]?.trim())
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
    /**
     * And ANCHORED to the bottom edge.
     *
     * This test asserted only the horizontal claim, so it passed while
     * the line ran across the middle of the pane: an absolutely
     * positioned element with no vertical anchor sits at its static
     * position, and the header centres its children.
     *
     * Checking half a rule is how a test confirms the part you
     * remembered and misses the part you forgot.
     */
    expect(seam).toMatch(/bottom:\s*0/)
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

describe('the breakpoint is one number', () => {
  it('the CSS overlay and the JS auto-collapse agree', () => {
    /**
     * They used to disagree: the sidebar auto-collapsed below 640px
     * while the CSS made it overlay below 1100. Between those widths
     * an expanded sidebar floated over the content and nothing
     * collapsed it, so the Back button and the left edge of every
     * screen sat underneath it.
     *
     * Read from both files, because a constant duplicated across a
     * stylesheet and a module is exactly the kind that drifts.
     */
    const shell = readFileSync(path.resolve(__dirname, './Shell.tsx'), 'utf8')

    // EVERY media query, not the first: there were three different
    // widths in this file, which is how they drifted apart.
    const cssWidths = [...CSS.matchAll(/^@media \(max-width: (\d+)px\)/gm)].map((m) => m[1])
    // Two media queries, one width -- distinct VALUES is the property.
    expect([...new Set(cssWidths)]).toHaveLength(1)
    const cssWidth = cssWidths[0]
    const jsWidth = /max-width: (\d+)px/.exec(shell)?.[1]

    expect(cssWidth).toBeDefined()
    expect(jsWidth).toBe(cssWidth)
  })

  it('an overlaid sidebar sits below the header, not over it', () => {
    // top: 0 covered the global header entirely -- product name, theme
    // toggle and user menu all vanished behind the expanded rail.
    const overlay =
      // Anchored on the SIDEBAR selector specifically -- an unanchored
      // match found the header rule that shares the same prefix.
      /--sidebar-collapsed\) \.app__sidebar \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(overlay).toMatch(/top:\s*48px/)
    expect(overlay).not.toMatch(/top:\s*0/)
  })
})

describe('schema tables have fixed columns', () => {
  it('does not let an empty column collapse', () => {
    /**
     * A Description column with nothing in it collapsed to the width
     * of its own header, so the header sat hard right against the
     * table edge -- and jumped left the moment one row had a
     * description. The heading appeared to move because the COLUMN
     * did.
     *
     * table-layout: fixed makes the widths a property of the table
     * rather than of whatever data happens to be in it.
     */
    const table = /\.schema-panel__fields \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(table).toMatch(/table-layout:\s*fixed/)
  })

  it('gives all three columns a width', () => {
    // Three tables share this class -- parameters, link types and
    // fields -- and all three have exactly the same shape: name, type,
    // description. Checked rather than assumed before writing widths
    // that apply to all of them.
    const widths = [...CSS.matchAll(/\.schema-panel__fields td:nth-child\((\d)\)/g)].map((match) => match[1])

    expect(new Set(widths)).toEqual(new Set(['1', '2', '3']))
  })
})
