/**
 * The token layers, and the rule that keeps them separate.
 *
 *   1. PRIMITIVES -- the raw ramp (--grey-700, --blue-400), named by
 *      what they ARE, never by what they are for.
 *   2. SEMANTIC   -- role names (--surface-chrome, --text-secondary).
 *      Every value is a primitive reference, never a literal.
 *   3. COMPONENT  -- what rules consume, already the case here.
 *
 * WITHOUT THE SEPARATION A THEME CHANGE TOUCHES EVERY TOKEN. That is
 * the whole argument, and it is why this is enforced rather than
 * intended: a literal creeping back into the semantic layer is
 * invisible until someone adds a third theme and finds one value that
 * will not move.
 *
 * ASSERTED AGAINST SOURCE TEXT, because jsdom computes no styles and
 * this repository has no computed-style assertions at all. That is a
 * real limitation: this proves STRUCTURE, not that anything renders.
 */

import { readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

/** Every component source, as [path, text]. For checks about what the
 *  whole app does rather than what one file does. */
function readAll(): Array<[string, string]> {
  const root = resolve(process.cwd(), 'packages')
  const out: Array<[string, string]> = []
  for (const pkg of readdirSync(root)) {
    const dir = resolve(root, pkg, 'src')
    let entries: string[]
    try {
      entries = readdirSync(dir)
    } catch {
      continue
    }
    for (const name of entries) {
      if (!name.endsWith('.tsx') || name.includes('.test.')) continue
      out.push([`${pkg}/src/${name}`, readFileSync(resolve(dir, name), 'utf8')])
    }
  }
  return out
}

const tokens = read('packages/shell-api/src/tokens.css')
const stylesheets = ['packages/shell-api/src/index.css', 'packages/app-schema/src/SchemaPanel.css'].map(read)

/** Declarations only, comments stripped, so prose about a colour is
 *  never mistaken for a colour. */
function declarations(css: string): string[] {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.startsWith('--') || /^[a-z-]+:/.test(line))
}

const PRIMITIVE = /^--(grey|blue|red|white)/

describe('token layers', () => {
  it('defines a ramp named by what the colours are', () => {
    expect(declarations(tokens).filter((line) => PRIMITIVE.test(line)).length).toBeGreaterThan(8)
  })

  it('gives every semantic token a primitive reference, never a literal', () => {
    // THE PROPERTY. A literal here is a primitive that escaped, and it
    // is the one value that will not move when a theme does.
    const offenders = declarations(tokens)
      .filter((line) => line.startsWith('--') && !PRIMITIVE.test(line))
      .filter((line) => /#[0-9a-fA-F]{3,8}/.test(line))

    expect(offenders).toEqual([])
  })

  it('keeps raw colours out of the stylesheets entirely', () => {
    // A hex in a rule is a decision made where nobody will look for
    // it -- which is how a destructive button became the one element
    // the token system did not describe.
    for (const css of stylesheets) {
      expect(declarations(css).filter((line) => /#[0-9a-fA-F]{3,8}/.test(line))).toEqual([])
    }
  })

  it('defines every token a stylesheet references', () => {
    // A var() naming a token that does not exist resolves to NOTHING
    // and inherits instead -- silently, no error anywhere. That is the
    // failure mode a rename causes, and the reason this test exists.
    const defined = new Set([...tokens.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((match) => match[1]))
    const used = new Set(
      stylesheets.flatMap((css) =>
        [...css.matchAll(/var\((--[a-z0-9-]+)/g)]
          .map((match) => match[1])
          .filter((token): token is string => token !== undefined),
      ),
    )
    // --pt-* are BLUEPRINT'S OWN, defined in the vendor layer.
    // SchemaPanel.css uses --pt-font-family-monospace rather than
    // inventing a second mono stack, which is correct.
    const ours = [...used].filter((token) => !token.startsWith('--pt-'))

    expect(ours.filter((token) => !defined.has(token))).toEqual([])
  })

  it('overrides only semantic tokens in the dark theme, never primitives', () => {
    // A dark theme redefining --grey-700 would change what the NAME
    // means rather than which grey a surface uses, and every other
    // consumer of that primitive would move with it.
    const darkBlock = tokens.slice(tokens.indexOf('.bp6-dark'))
    const overridden = [...darkBlock.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((m) => m[1] ?? '')

    expect(overridden.filter((token) => PRIMITIVE.test(token))).toEqual([])
    expect(overridden.length).toBeGreaterThan(4)
  })
})

describe('element selectors do not describe Blueprint widgets', () => {
  /**
   * THE BUG THIS GUARDS. index.css carried a bare `button { background:
   * var(--surface-chrome) }`. Blueprint renders a real <button>, and
   * --surface-chrome is dark in BOTH themes because it is furniture --
   * so every Blueprint button in the app rendered dark-on-light.
   *
   * AN ELEMENT SELECTOR IS THE ONE THING A COMPONENT CANNOT OPT OUT OF.
   * A class can be not-applied and a variable can be overridden, but a
   * bare `button` rule reaches every button that will ever exist,
   * including ones the library owns. That is why this is worth a test
   * rather than a convention.
   *
   * `a` is excluded: Blueprint's AnchorButton aside, links are ours to
   * style and there is no bare `a` rule today anyway.
   */
  const OWNED_BY_BLUEPRINT = ['button', 'select', 'input', 'textarea', 'table']

  /**
   * ONE EXCEPTION, and the distinction matters. A bare selector
   * imposing our DESIGN on a Blueprint widget is the bug. A bare
   * selector enforcing an accessibility FLOOR across everything is
   * legitimate and should reach Blueprint's widgets too -- the
   * min-height rule applying WCAG 2.2's target size is exactly that.
   *
   * Distinguished by what the rule DECLARES, not by what it selects.
   */
  const ACCESSIBILITY_FLOOR = /min-height|min-width|outline/

  it('declares no bare rule imposing our design on an element Blueprint renders', () => {
    for (const css of stylesheets) {
      const blocks = css.replace(/\/\*[\s\S]*?\*\//g, '').split('}')
      const offenders = blocks.filter((block) => {
        const selector = block.split('{')[0] ?? ''
        const body = block.split('{')[1] ?? ''
        const bare = selector
          .split(',')
          .map((part) => part.trim())
          .some((part) => OWNED_BY_BLUEPRINT.includes(part))
        return bare && !ACCESSIBILITY_FLOOR.test(body)
      })

      expect(offenders).toEqual([])
    }
  })
})

describe('layout responds to the canvas, not the viewport', () => {
  /**
   * A media query asks how wide the VIEWPORT is. What decides whether a
   * two-column workspace fits is how wide the CANVAS is, and those are
   * different numbers whenever the sidebar is open -- at a 1200px
   * viewport with the sidebar out, the canvas is about 900px.
   *
   * The distinction is not stylistic. It will widen further once the
   * sidebar collapses per sub-app, and again if an inspector is added.
   */
  const shell = read('packages/shell-api/src/index.css')

  it('declares the canvas as a named query container', () => {
    // NAMED, so a query reads as asking about the canvas rather than
    // about whichever ancestor happens to be nearest -- which changes
    // silently when someone adds a container in between.
    expect(shell).toMatch(/\.app__content\s*\{[^}]*container-name:\s*canvas/s)
    expect(shell).toMatch(/\.app__content\s*\{[^}]*container-type:\s*inline-size/s)
  })

  it('sizes the workspace against the canvas', () => {
    expect(shell).toMatch(/@container canvas \(max-width/)
  })

  it('does not decide the workspace layout from the viewport', () => {
    // THE REGRESSION THIS GUARDS. A media query reintroduced here
    // would work at most viewport widths and fail precisely when the
    // sidebar is open -- the case nobody tests by hand, because the
    // window looks plenty wide.
    const mediaBlocks = [...shell.matchAll(/@media[^{]*\{([\s\S]*?)\n\}/g)].map((m) => m[1] ?? '')

    expect(mediaBlocks.filter((body) => body.includes('.workspace'))).toEqual([])
  })
})

describe('scrolling stays where it was started', () => {
  /**
   * THE SHELL HAS FIVE INDEPENDENT SCROLL CONTAINERS: the sidebar, the
   * canvas main, the workspace config pane, the workspace content, and
   * the graph preview. Each one can reach its end while the reader is
   * still inside it.
   *
   * Without containment, reaching that end hands the wheel to the
   * parent and the page moves under the cursor -- the reader loses
   * their place in a list they were not trying to leave. It reads as
   * the app being twitchy rather than as a bug worth reporting, which
   * is why it survives.
   */
  const shell = read('packages/shell-api/src/index.css')

  it('contains scroll in every pane that scrolls', () => {
    // Counted rather than spot-checked: a new scrolling pane added
    // without containment is the regression, and naming the current
    // five would not catch a sixth.
    // COMMENTS STRIPPED FIRST. A comment in this file discusses
    // "overflow-y: auto never engages because nothing constrains
    // them", and counting prose as code made this assert 6 against 5.
    // The token tests above strip comments for the same reason.
    const rules = shell.replace(/\/\*[\s\S]*?\*\//g, '')
    const scrollers = [...rules.matchAll(/overflow-y:\s*auto/g)].length
    const contained = [...rules.matchAll(/overscroll-behavior:\s*contain/g)].length

    expect(scrollers).toBeGreaterThan(0)
    expect(contained).toBe(scrollers)
  })

  it('keeps the reader in place when content loads above them', () => {
    // A chart resolving, a freshness note appearing, a Callout
    // replacing a spinner -- all insert content ABOVE what someone is
    // reading. Declared rather than left to the default, so nobody
    // turns it off further down without meeting the comment.
    expect(shell).toMatch(/overflow-anchor:\s*auto/)
  })
})

describe('identifiers are readable as identifiers', () => {
  /**
   * UI_ROADMAP.md item 8: "IDs monospace with a copy affordance".
   *
   * An object id is read to COMPARE and to COPY -- is this the same
   * cust_001 I was looking at, did I select all of it. Proportional
   * type makes both harder: 1/l/I and 0/O collapse together, and two
   * ids of equal length render different widths.
   */
  const tokens = read('packages/shell-api/src/tokens.css')
  const shell = read('packages/shell-api/src/index.css')

  it('declares a monospace stack as a primitive', () => {
    // A PRIMITIVE, not an override. Blueprint ships no monospace
    // token, so there is nothing to override -- and a raw font stack
    // inside one component rule is what the token layer exists to
    // prevent.
    expect(tokens).toMatch(/--font-mono:/)
  })

  it('uses the system stack rather than a webfont', () => {
    // A webfont for an id is weight paid on the first paint of every
    // page, for glyphs every platform already has.
    expect(tokens).toMatch(/ui-monospace/)
    expect(tokens).not.toMatch(/--font-mono:[^;]*url\(/)
  })

  it('renders the object id in it', () => {
    expect(shell).toMatch(/\.object-detail__subtitle\s*\{[^}]*font-family:\s*var\(--font-mono\)/s)
  })

  it('makes one click select the whole id', () => {
    // THE COPY AFFORDANCE. An id is never usefully selected in part,
    // and a double-click otherwise stops at the underscore in
    // cust_001 -- giving "cust" and a silent mistake downstream.
    expect(shell).toMatch(/\.object-detail__subtitle\s*\{[^}]*user-select:\s*all/s)
  })
})

describe('one loading treatment, used everywhere', () => {
  /**
   * Three existed across six components. The consolidation is only
   * worth anything if it holds, and a seventh hand-rolled one would be
   * as easy to add as the sixth was.
   */
  const shell = read('packages/shell-api/src/index.css')

  it('hides the label from sight without hiding it from a reader', () => {
    // display:none and visibility:hidden both remove an element from
    // the accessibility tree. The clip-rect technique does not, which
    // is the entire reason this class exists rather than either.
    expect(shell).toMatch(/\.visually-hidden\s*\{[^}]*clip:\s*rect/s)
    expect(shell).not.toMatch(/\.visually-hidden\s*\{[^}]*display:\s*none/s)
    expect(shell).not.toMatch(/\.visually-hidden\s*\{[^}]*visibility:\s*hidden/s)
  })
})

describe('every error is announced, not just shown', () => {
  /**
   * A danger Callout sets no ARIA role, so an error rendered directly
   * with one is silent to a screen reader. Ten components did that
   * before ErrorState existed.
   *
   * This is the guard that keeps an eleventh from being added the same
   * way -- the loading consolidation showed how quickly a shared
   * treatment drifts once one component opts out.
   */
  const sources = readAll()

  it('no component renders a bare danger Callout', () => {
    const offenders = sources.filter(([, text]) => text.includes('<Callout intent="danger"')).map(([path]) => path)

    expect(offenders).toEqual([])
  })
})

describe("a descendant selector must not claim other components' elements", () => {
  /**
   * `.workspace__filter > label` matched EVERY direct child label --
   * and Blueprint's Checkbox IS a label. So each checkbox in the
   * Columns filter was given the filter-heading treatment: uppercase,
   * bold, and stacked so the box sat above its own text.
   *
   * That was reported as "checkboxes above their text throughout the
   * UI", and a sweep for `<Checkbox` found nothing because the cause
   * was in shared CSS rather than in any component.
   *
   * WHAT THIS CAN AND CANNOT CHECK. jsdom computes no layout, so
   * nothing here proves anything LOOKS right. What it checks is that a
   * broad element selector carries an exclusion -- the specific
   * mistake that made a shared style reach into a component that
   * brings its own.
   */
  const shell = read('packages/shell-api/src/index.css')

  it('the filter heading style excludes Blueprint controls', () => {
    expect(shell).toContain('.workspace__filter > label:not(.bp6-control)')
  })

  it('no bare `> label` rule remains under workspace__filter', () => {
    // THE CONTROL on the fix. Re-adding the unqualified rule would
    // reintroduce the bug while the test above still passed, because
    // both rules could coexist.
    expect(shell).not.toMatch(/\.workspace__filter > label\s*\{/)
  })
})
