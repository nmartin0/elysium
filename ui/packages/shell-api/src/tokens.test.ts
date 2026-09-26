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

  it('references every token it defines', () => {
    // THE CONVERSE (09-S2-02), and it belongs here rather than in a
    // file of its own: the test above already computes both sets, and
    // two halves of one property kept apart is the drift both exist
    // to prevent.
    //
    // A token defined and never read is not harmless. tokens.css is
    // read as the vocabulary -- someone scanning it for "the token
    // for a control border" finds --border-control and uses it,
    // believing it is the established answer, when nothing has ever
    // rendered with it.
    //
    // THREE WERE UNREAD, and the third is why this pairs with the
    // dead-rule check in theme.test.ts: --text-on-danger and
    // --fill-danger existed only for `button.danger`, a rule whose
    // markup had already gone. A dead rule keeps its tokens looking
    // alive, so neither guard finds that pair alone.
    const defined = new Set([...tokens.matchAll(/^\s*(--[a-z0-9-]+)\s*:/gm)].map((match) => match[1]))
    // EVERY PLACE A TOKEN CAN BE READ, and tokens.css is one of them:
    // the semantic layer consumes the primitives, so leaving it out
    // would report every --grey-* and --blue-* as unread. Found by
    // doing exactly that.
    const referenced = new Set(
      [tokens, ...stylesheets, read('src/layers.css')].flatMap((css) =>
        [...css.matchAll(/var\(\s*(--[a-z0-9-]+)/g)]
          .map((match) => match[1])
          .filter((token): token is string => token !== undefined),
      ),
    )
    // And by name from a module: a few are read or set from JS rather
    // than through var().
    const byName = new Set(
      readAll().flatMap(([, source]) =>
        [...source.matchAll(/['"`](--[a-z0-9-]+)['"`]/g)]
          .map((match) => match[1])
          .filter((token): token is string => token !== undefined),
      ),
    )

    // AND IT MUST FIND THEM: an empty `defined` would pass vacuously.
    expect(defined.size).toBeGreaterThan(20)
    expect(referenced.size).toBeGreaterThan(20)

    // PRIMITIVES ARE EXEMPT, and the reason is the whole judgement in
    // this test. Layer 1 is a RAMP -- a palette declared once, named
    // by what the colours ARE. Layer 2 is role names, which must have
    // a consumer or they are vocabulary with no meaning.
    //
    // FOUND BY DELETING THE THREE UNREAD SEMANTIC TOKENS: it orphaned
    // --red-500 and --grey-300 underneath them. Deleting those in turn
    // would have taken the ONLY red out of the palette -- and
    // --red-500 is #b3261e, the exact literal index.css carried before
    // the token system absorbed it. The next person needing a
    // destructive colour would have had no red to reach for and would
    // have written the hex, which is the regression the palette exists
    // to prevent and which 'keeps raw colours out of the stylesheets
    // entirely' above would then have caught one commit too late.
    //
    // So an unread PRIMITIVE is a palette entry nobody has needed yet.
    // An unread SEMANTIC token is rot. Only the second is an error.
    //
    // NOTED, NOT FIXED: --grey-300 is now the one gap in an otherwise
    // contiguous ramp, and it is also the only grey with no blue cast
    // (#999999 against #abb3bf and #5f6b7c either side), which
    // DEV_UI 8.1 says the darks want. That looks like a mistake in the
    // ramp rather than an unused step, but it is a palette decision
    // and not this commit's business.
    const unread = [...defined].filter(
      (token): token is string =>
        token !== undefined && !PRIMITIVE.test(token) && !referenced.has(token) && !byName.has(token),
    )

    expect(unread).toEqual([])
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
    const mediaBlocks = [...shell.matchAll(/@media[^{]*\{([\s\S]*?)\n\s*\}/g)].map((m) => m[1] ?? '')

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

  it('the global label rule excludes Blueprint controls', () => {
    /** THE RULE THAT ACTUALLY CAUSED IT, and I guarded the wrong one
     *  first.
     *
     *  A bare `label { display: flex; flex-direction: column }` styled
     *  EVERY label in the app -- and Blueprint renders a Checkbox as a
     *  label wrapping an input, so the box was stacked above its own
     *  text everywhere. Blueprint's own stylesheet is never imported
     *  here, so nothing put it back.
     *
     *  My first fix scoped `.workspace__filter > label`, which only
     *  set typography. It changed nothing a person could see.
     */
    expect(shell).toMatch(/^\s*label:not\(\.bp6-control\) \{/m)
  })

  it('Blueprint controls get an inline layout of their own', () => {
    // Because Blueprint's stylesheet is not imported, excluding them
    // from the stacking rule leaves them with NO layout at all. The
    // replacement has to be stated rather than assumed.
    expect(shell).toMatch(/label\.bp6-control \{/)
  })

  it('the filter heading style excludes Blueprint controls', () => {
    expect(shell).toContain('.workspace__filter > label:not(.bp6-control)')
  })

  it('no bare `> label` rule remains under workspace__filter', () => {
    // THE CONTROL on the fix. Re-adding the unqualified rule would
    // reintroduce the bug while the test above still passed, because
    // both rules could coexist.
    expect(shell).not.toMatch(/\.workspace__filter > label\s*\{/)
    // AND THE GLOBAL ONE, which is the rule that mattered.
    expect(shell).not.toMatch(/^\s*label \{/m)
  })
})

describe('bare element selectors, which silently outrank Blueprint', () => {
  /**
   * THE MECHANISM, and it is not specificity. `.bp6-control` is more
   * specific than `label` and still loses: Blueprint sits in the
   * `vendor` layer (ui/src/layers.css) while our stylesheets are
   * UNLAYERED, and unlayered styles beat every layer.
   *
   * So any bare element selector we write overrides Blueprint's own
   * component styling however carefully Blueprint wrote it -- and it
   * does so invisibly, because nothing in this repository computes
   * styles or takes screenshots.
   *
   * That is how `label { display: flex; flex-direction: column }`
   * stacked every checkbox above its own text, app-wide, and why a
   * sweep for `<Checkbox` found nothing.
   *
   * THIS TEST IS A TRIPWIRE, not a prohibition. Bare element selectors
   * are legitimate for genuine defaults. The list is explicit so that
   * ADDING one is a decision someone makes on purpose, with this
   * comment in front of them.
   */
  const shell = read('packages/shell-api/src/index.css')

  const ALLOWED = new Set(['body', 'form', 'label:not(.bp6-control)', 'label.bp6-control', 'button.danger'])

  it('only the reviewed ones exist', () => {
    const found = [...shell.matchAll(/^\s*([a-z][a-z0-9]*[a-z0-9:().,#_ -]*)\{/gm)]
      .map((match) => match[1]!.trim())
      .filter((selector) => !selector.includes('@'))

    const unreviewed = found.filter((selector) => !ALLOWED.has(selector))

    expect(unreviewed).toEqual([])
  })

  it('a rule that reaches into Blueprint says which class', () => {
    // Every .bp6- rule is a deliberate reach into a vendor component.
    // Requiring the class to be named rather than matched by prefix
    // keeps them greppable when Blueprint's next major renames them.
    expect(shell).not.toMatch(/\[class\^=["']bp6/)
  })
})

describe('a card holding a control must not stretch its link', () => {
  /**
   * `::after { inset: 0 }` makes a whole card a link target. That is a
   * good pattern for a card that is ONLY a link, and incompatible with
   * one holding a checkbox: the overlay either swallows the control's
   * clicks or must be out-stacked by it, and every interaction that is
   * not a plain left-click then needs reasoning about separately.
   *
   * IT COST THREE FAILED FIXES. Plain clicks selected correctly
   * because z-index resolved that case; shift-clicking the checkbox
   * NAVIGATED, which only a server log revealed -- GET
   * /objects/Transaction/4 arriving during a selection test.
   *
   * Nothing in this repository computes layout or hit-testing, so this
   * guards the CAUSE rather than the symptom.
   */
  const shell = read('packages/shell-api/src/index.css')

  it('the result card has no stretched link overlay', () => {
    expect(shell).not.toMatch(/\.object-search__link::after/)
  })

  it('and the checkbox no longer needs its own stacking context', () => {
    // Keeping one that guards against nothing is how the next reader
    // concludes it is load-bearing and works around it.
    // A DECLARATION, not the word. The block's own comment explains
    // why the z-index went, so matching the bare word finds the
    // explanation and calls it the thing it explains.
    const block = shell.slice(
      shell.indexOf('.object-search__select {'),
      shell.indexOf('}', shell.indexOf('.object-search__select {')),
    )
    expect(block).not.toMatch(/^\s*z-index:/m)
  })
})

describe('the selection checkbox is a plain input', () => {
  /**
   * NOT Blueprint's Checkbox, and this guards the reason rather than
   * the symptom.
   *
   * Blueprint renders a Checkbox as a <label> wrapping a hidden input
   * and a visible indicator span. Any click inside that label forwards
   * a SECOND click to the input, so one gesture produced two events
   * and the selection toggled twice.
   *
   * Four commits tried to tell them apart -- by target, by target plus
   * a flag, then by a 50ms window. The window made clicks
   * intermittently do nothing, because a real click landing inside it
   * was mistaken for a forward. Timing cannot distinguish a fast user
   * from a browser.
   *
   * A bare input has one click target and needs none of it.
   */
  const panel = read('packages/app-browse/src/ObjectSearchPanel.tsx')

  it('does not render Blueprint Checkbox for a result row', () => {
    // The Columns filter still uses one, and should: it has a visible
    // text label and no competing click target.
    // `<input type="checkbox"` immediately before the row's own
    // class, which is the order the file has and a <Checkbox> could
    // never produce.
    expect(panel).toMatch(/<input\s+type="checkbox"\s+className="object-search__select"/)
  })

  it('keeps no forwarded-click bookkeeping', () => {
    // A guard against the mechanism creeping back in alongside the
    // input, which would reintroduce the intermittency it caused.
    expect(panel).not.toMatch(/forwardedClick|forwardedAfter/)
  })
})
