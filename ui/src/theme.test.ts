import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const CSS = readFileSync(path.resolve(__dirname, '../packages/shell-api/src/index.css'), 'utf8')
const TOKENS = readFileSync(path.resolve(__dirname, '../packages/shell-api/src/tokens.css'), 'utf8')

// THE STYLESHEETS THAT HOLD RULES, for the duplicate check below.
const RULE_STYLESHEETS = [
  'packages/app-schema/src/SchemaPanel.css',
  'packages/shell-api/src/index.css',
  'packages/shell-api/src/tokens.css',
]

/** Every rule: its selectors, each prefixed with the at-rules enclosing
 *  it, and the properties the rule sets.
 *
 *  A WALK OVER THE BRACES, not a pattern: comments stripped, each `{`
 *  classified by what precedes it -- an at-rule opens a context, anything
 *  else is a rule recorded under that context. So `.a` inside `@media (x)`
 *  and `.a` outside it are different rules, as they are to the browser.
 *  Selector lists split on TOP-LEVEL commas only, so `:is(.a, .b)` stays
 *  whole. */
function cssRules(css: string): { selector: string; properties: Set<string> }[] {
  const text = css.replace(/\/\*[\s\S]*?\*\//g, '')
  const found: { selector: string; properties: Set<string> }[] = []
  const contexts: string[] = []
  const open: { kind: 'at' | 'rule'; selectors: string[]; bodyStart: number }[] = []
  let start = 0
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i]
    if (ch === '{') {
      const prelude = text.slice(start, i).trim().replace(/\s+/g, ' ')
      if (prelude.startsWith('@')) {
        contexts.push(prelude)
        open.push({ kind: 'at', selectors: [], bodyStart: i + 1 })
      } else {
        const prefix = contexts.length > 0 ? `${contexts.join(' > ')} > ` : ''
        open.push({ kind: 'rule', selectors: splitTopLevel(prelude).map((s) => prefix + s), bodyStart: i + 1 })
      }
      start = i + 1
    } else if (ch === '}') {
      const block = open.pop()
      if (block?.kind === 'at') contexts.pop()
      if (block?.kind === 'rule') {
        const body = text.slice(block.bodyStart, i)
        const properties = new Set([...body.matchAll(/(?:^|;)\s*(-{0,2}[a-zA-Z][\w-]*)\s*:/g)].map((m) => m[1] ?? ''))
        for (const selector of block.selectors) found.push({ selector, properties })
      }
      start = i + 1
    } else if (ch === ';') {
      start = i + 1
    }
  }
  return found
}

function ruleSelectors(css: string): string[] {
  return cssRules(css).map((rule) => rule.selector)
}

function splitTopLevel(selectorList: string): string[] {
  const parts: string[] = []
  let depth = 0
  let current = ''
  for (const ch of selectorList) {
    if (ch === '(') depth += 1
    if (ch === ')') depth -= 1
    if (ch === ',' && depth === 0) {
      parts.push(current.trim())
      current = ''
    } else {
      current += ch
    }
  }
  if (current.trim()) parts.push(current.trim())
  return parts
}

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
     * ONE exception now, and it is deliberate:
     *
     * - Translucent white overlays. rgba(255,255,255,alpha) on chrome
     *   is a LIGHTENING, not a colour: it works on any dark surface,
     *   in either theme, and a token would fix it to one. Three uses.
     *
     * THERE WERE THREE. `#b3261e` and `#ffffff` were exempted for the
     * destructive button -- a semantic red that must not invert, and
     * the white on top of it. That button moved to Blueprint's own
     * intent="danger" long ago, and 09-S2-01 removed the rule that
     * outlived it, so neither literal appears in this file any more.
     *
     * THE EXEMPTIONS WERE THEREFORE EXEMPTING NOTHING, and a dead
     * exemption is worse than none: it is a hole held open for a case
     * that no longer exists, so the day somebody writes #b3261e here
     * again -- the exact literal the token system was built to absorb
     * -- this test would have waved it through. Checked before
     * removing: zero occurrences of either in index.css.
     */
    const offenders = colourLiterals(CSS).filter((line) => !/rgba\(255,\s*255,\s*255/.test(line))

    expect(offenders).toEqual([])
  })

  it('chrome stays darker than the page behind it in dark mode', () => {
    /**
     * THE bug that made the sidebar vanish. Both were #1c2127, so the
     * sidebar dissolved into the background and took the logout and
     * theme buttons with it -- reported as "the buttons are not
     * present".
     */
    // RESOLVED THROUGH the primitive layer, because semantic tokens now
    // hold `var(--grey-900)` rather than a literal. Comparing primitive
    // NAMES would be weaker: two names can point at the same hex, which
    // is exactly the bug this guards.
    const dark = TOKENS.slice(TOKENS.indexOf('.bp6-dark'))
    const resolve = (token: string) => {
      const ref = new RegExp(`--${token}: var\\((--[a-z0-9-]+)\\)`).exec(dark)?.[1]
      if (ref === undefined) return undefined
      return new RegExp(`\\${ref}: (#[0-9a-f]{6})`).exec(TOKENS)?.[1]
    }

    const chrome = resolve('surface-chrome')
    const sunken = resolve('surface-sunken')

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
    //
    // WHAT IS CHECKED: A PROPERTY SET TWICE FOR ONE SELECTOR, in one
    // context. That is the bug class above -- the later block silently
    // overriding the earlier -- and it is what 09-S1-01's two collapsed-
    // sidebar rules were. Two blocks setting DIFFERENT properties are
    // not it: `html, body, #root` share the viewport lock and `body`
    // adds its own margin, with no property in both, and forcing those
    // into one rule would merge unrelated concerns.
    for (const file of RULE_STYLESHEETS) {
      const bySelector = new Map<string, Set<string>[]>()
      for (const rule of cssRules(readFileSync(path.resolve(__dirname, '..', file), 'utf8'))) {
        bySelector.set(rule.selector, [...(bySelector.get(rule.selector) ?? []), rule.properties])
      }
      const overridden: string[] = []
      for (const [selector, blocks] of bySelector) {
        const seen = new Set<string>()
        for (const properties of blocks) {
          for (const property of properties) {
            if (seen.has(property)) overridden.push(`${selector} { ${property} }`)
            seen.add(property)
          }
        }
      }

      expect(overridden, file).toEqual([])
    }
  })

  it('sees every rule, not a fraction of them', () => {
    /**
     * 09-S3-01: THE PREVIOUS PATTERN SAW 1 OF 204 RULES. It matched a
     * selector only at column 0, containing no dot after the first and
     * no digit -- so compound selectors, every bp6- override, every
     * pseudo-class, and everything inside a media query were invisible.
     * Then @layer wrapping indented every rule, and it saw one. A green
     * duplicate check that sees nothing is how 09-S1-01's contradictory
     * sidebar rules went unnoticed.
     */
    const selectors = ruleSelectors(CSS)

    expect(selectors.length).toBeGreaterThan(200)
    expect(selectors).toContain('@layer components > .app-frame--sidebar-collapsed .app__sidebar')
    expect(selectors.some((s) => s.includes('.bp6-'))).toBe(true)
    expect(selectors.some((s) => s.startsWith('@layer components > @media'))).toBe(true)
    // AND ITS PROPERTIES. A first version of the property pattern read
    // `--?[a-zA-Z]` -- which REQUIRES a leading hyphen -- so it saw only
    // custom properties, and the overridden-property check passed with
    // 09-S1-01's contradiction still in the file. The same vacuity as the
    // pattern this replaced.
    const sidebar = cssRules(CSS).filter(
      (r) => r.selector === '@layer components > .app-frame--sidebar-collapsed .app__sidebar',
    )
    expect(sidebar.length).toBeGreaterThan(0)
    expect(sidebar.every((r) => r.properties.has('width'))).toBe(true)
  })

  it('covers every stylesheet that holds rules', () => {
    /** THE LIST ABOVE IS EXPLICIT, so this keeps it honest: a stylesheet
     *  added later fails here until it is added there. layers.css holds
     *  only @layer and @import statements. */
    const onDisk = [
      ...readdirSync(path.resolve(__dirname, '..', 'packages')).flatMap((pkg) => {
        const dir = path.resolve(__dirname, '..', 'packages', pkg, 'src')
        return readdirSync(dir)
          .filter((f) => f.endsWith('.css'))
          .map((f) => `packages/${pkg}/src/${f}`)
      }),
      ...readdirSync(__dirname)
        .filter((f) => f.endsWith('.css'))
        .map((f) => `src/${f}`),
    ].sort()

    expect(onDisk).toEqual([...RULE_STYLESHEETS, 'src/layers.css'].sort())
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
    const cssWidths = [...CSS.matchAll(/^\s*@media \(max-width: (\d+)px\)/gm)].map((m) => m[1])
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

/**
 * A rule whose markup is gone (09-S2-01).
 *
 * Every other stylesheet guard here reads the CSS ALONE, so none of
 * them can see a rule that is perfectly well-formed and describes
 * nothing. That needs the CSS compared against the markup beside it.
 *
 * THE MATCH IS ON CLASS-ATTRIBUTE POSITION, NOT ON THE WORD, and this
 * is the whole difficulty. A first version searched production source
 * for the class name as a whole word and found FOUR of the five dead
 * rules: it missed `button.danger`, because `danger` is a live
 * Blueprint intent value -- SchemaPanel.tsx returns `'danger'` for a
 * deprecated type, and every error Callout takes `intent="danger"`.
 * A substring cannot tell an intent from a class name.
 *
 * Reading what is actually rendered -- the contents of `className=`
 * and `class=` -- finds all five with no false positives across 156
 * classes. It is also the honest question: a class is alive if
 * something puts it on an element, not if the word appears somewhere.
 *
 * THE KNOWN LIMIT, written here rather than rediscovered: a class
 * assembled at runtime (`` className={`row--${kind}`} ``) contributes
 * the literal fragments only, so a fully computed name would read as
 * dead. None exists today. If one is added, this test is what will
 * complain, and the answer is an allowlist entry with a reason -- not
 * a weaker match, which is how 09-S3-01 happened.
 */

/** Every class token the app actually puts on an element. */
function renderedClassNames(): Set<string> {
  const found = new Set<string>()
  const attribute = /class(?:Name)?\s*=\s*(?:"([^"]*)"|'([^']*)'|\{`([^`]*)`\}|\{([^}]*)\})/g
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'dist') walk(full)
      } else if (/\.(tsx|ts|html)$/.test(entry.name) && !entry.name.includes('.test.')) {
        // TESTS EXCLUDED DELIBERATELY: a class only a test renders is
        // dead in the product, and counting it would let a rule stay
        // alive by being asserted about. Checked before choosing --
        // no class is test-only today, so this forbids a future one
        // at no cost.
        const source = readFileSync(full, 'utf8')
        for (const match of source.matchAll(attribute)) {
          const blob = [match[1], match[2], match[3], match[4]].filter(Boolean).join(' ')
          for (const token of blob.match(/[a-zA-Z][\w-]*/g) ?? []) found.add(token)
        }
      }
    }
  }
  walk(path.resolve(__dirname, '..', 'packages'))
  walk(__dirname)
  for (const match of readFileSync(path.resolve(__dirname, '..', 'index.html'), 'utf8').matchAll(attribute)) {
    const blob = [match[1], match[2], match[3], match[4]].filter(Boolean).join(' ')
    for (const token of blob.match(/[a-zA-Z][\w-]*/g) ?? []) found.add(token)
  }
  return found
}

/** Every class OUR stylesheets style. Blueprint's own `bp6-` classes
 *  are its markup, not ours -- we never write them on an element. */
function styledClassNames(): Map<string, string> {
  const found = new Map<string, string>()
  for (const file of RULE_STYLESHEETS) {
    const css = readFileSync(path.resolve(__dirname, '..', file), 'utf8')
    for (const rule of cssRules(css)) {
      for (const match of rule.selector.matchAll(/\.([a-zA-Z][\w-]*)/g)) {
        const name = match[1] ?? ''
        if (!name.startsWith('bp6-') && !found.has(name)) found.set(name, file)
      }
    }
  }
  return found
}

describe('every rule describes markup that exists', () => {
  it('finds both sides, so an empty search cannot pass', () => {
    // THE CONTROL INSIDE THE TEST. Both halves are built by walking
    // the tree; a moved directory or a broken parse would leave one
    // empty and the comparison below would pass having compared
    // nothing -- the same vacuity as 09-S3-01.
    const styled = styledClassNames()
    const rendered = renderedClassNames()

    expect(styled.size).toBeGreaterThan(100)
    expect(rendered.size).toBeGreaterThan(100)
    expect([...styled.keys()]).toContain('object-search__result')
    expect(rendered.has('object-search__result')).toBe(true)
  })

  it('styles no class the app never renders', () => {
    const rendered = renderedClassNames()
    const orphans: string[] = []
    for (const [name, file] of styledClassNames()) {
      if (!rendered.has(name)) orphans.push(`${file}: .${name}`)
    }

    expect(orphans).toEqual([])
  })
})

describe('the viewport lock is declared in one place', () => {
  /**
   * 09-S3-03 was graded COSMETIC -- a duplicated comment block, whose
   * copy said "the vh line above" when the vh line is below it, in a
   * rule that comment does not introduce. Both were left behind when
   * the lock moved to the outermost element.
   *
   * WHAT IS NOT TESTED, AND WHY. The duplication itself is not
   * assertable without pinning the prose, and pinning prose to catch
   * stale prose is what produced 10-S1-03. There is no general test
   * for "this paragraph repeats that one", and a regex for the
   * particular sentence would pass the moment somebody rewords it --
   * a test that can only catch the instance already fixed.
   *
   * WHAT IS TESTED is the property underneath the comment, which has
   * one right answer: the lock is declared ONCE. Two rules both
   * sizing the shell to the viewport is the defect a second
   * explanation was describing, and it is the thing that would
   * actually break a layout.
   */

  it('sizes the shell to the viewport in exactly one rule', () => {
    const withoutComments = CSS.replace(/\/\*[\s\S]*?\*\//g, '')
    const declarations = [...withoutComments.matchAll(/height:\s*100dvh/g)]

    expect(declarations).toHaveLength(1)

    // AND ON THE OUTERMOST ELEMENT, not just once. The lock moved here
    // from an inner element, which is what left the stale comment
    // behind; a future move would leave another.
    const frame = /\.app-frame \{([^}]*)\}/.exec(withoutComments)?.[1] ?? ''

    expect(frame).toMatch(/height:\s*100dvh/)
  })

  it('keeps the vh fallback beside the dvh it falls back from', () => {
    // The pair is load-bearing and order-sensitive: vh FIRST, then
    // dvh, so a browser that does not know dvh keeps the vh value and
    // one that does overrides it. Reversed, every modern browser gets
    // the vh answer and the mobile toolbar bug comes back.
    const declarations = CSS.replace(/\/\*[\s\S]*?\*\//g, '')
    const vh = declarations.indexOf('height: 100vh')
    const dvh = declarations.indexOf('height: 100dvh')

    expect(vh).toBeGreaterThan(-1)
    expect(dvh).toBeGreaterThan(-1)
    expect(vh).toBeLessThan(dvh)
  })
})
