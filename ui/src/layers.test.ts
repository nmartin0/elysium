/**
 * The cascade order survives the build.
 *
 * THE TRAP THIS GUARDS. Unlayered styles beat EVERY layer. So
 * importing Blueprint plainly while putting our own CSS in a layer
 * would silently invert the entire override order: Blueprint would win
 * everything, the test suite would stay green, and the app would look
 * wrong. Nothing else in this repository can catch that -- there are no
 * computed-style assertions and no screenshot tests.
 *
 * Asserted against the SOURCE rather than the built bundle, because a
 * unit test cannot run vite. The build output was checked by hand once
 * and behaved as intended: the bundler hoists `@layer vendor{` to
 * position 0 and rewrites the ordering statement without `vendor`,
 * since the block already established it first.
 */

import { readdirSync, readFileSync } from 'node:fs'
import { join, resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

// Relative to the vitest root (ui/), not to this file: import.meta.url
// is not a file URL under vitest's transform.
const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

// Every .css under src/ and each package's src/, relative to ui/. (A
// block comment here once ended early: "packages/*" + "/src" is "*/".)
function allStylesheets(): string[] {
  const found: string[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(resolve(process.cwd(), dir), { withFileTypes: true })) {
      const path = join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules') walk(path)
      } else if (entry.name.endsWith('.css')) {
        found.push(path)
      }
    }
  }
  walk('src')
  for (const pkg of readdirSync(resolve(process.cwd(), 'packages'))) walk(join('packages', pkg, 'src'))
  return found.sort()
}

const layers = read('src/layers.css')
const app = read('src/App.tsx')

describe('cascade layers', () => {
  it('declares the order before importing anything', () => {
    // @layer must precede @import, per the spec: an @import after any
    // rule other than @charset or a @layer statement is dropped.
    expect(layers.indexOf('@layer vendor,')).toBeLessThan(layers.indexOf('@import'))
  })

  it('puts Blueprint in the vendor layer rather than leaving it unlayered', () => {
    // THE PROPERTY. Unlayered would beat every layer below it.
    expect(layers).toMatch(/@import\s+url\([^)]*blueprint\.css[^)]*\)\s+layer\(vendor\)/)
  })

  it('is the only place Blueprint CSS is imported', () => {
    // A second, plain import elsewhere would reintroduce an unlayered
    // copy -- and unlayered wins, so the layered one would stop
    // mattering entirely.
    expect(app).not.toMatch(/import\s+'@blueprintjs\/core\/lib\/css\/blueprint\.css'/)
  })

  it('orders vendor first, so everything can override it', () => {
    const matched = layers.match(/@layer ([^;]+);/)
    if (matched === null) throw new Error('no @layer statement in layers.css')

    const order = (matched[1] ?? '').split(',').map((n) => n.trim())
    expect(order[0]).toBe('vendor')
    expect(order).toContain('components')
  })

  it('keeps !important out of the UI', () => {
    // The reason layers are worth having. Zero today; a layer order is
    // what lets that stay true while sitting beside a library with
    // high-specificity selectors.
    // EVERY STYLESHEET, found rather than listed (09-S3-02). The list
    // named three files and missed layers.css -- the one whose purpose
    // is making !important unnecessary -- and would have missed any
    // stylesheet added later.
    const cssFiles = allStylesheets()
    // AND IT MUST FIND THEM: an empty search passes vacuously.
    expect(cssFiles).toEqual(
      expect.arrayContaining([
        'src/layers.css',
        'packages/shell-api/src/index.css',
        'packages/shell-api/src/tokens.css',
        'packages/app-schema/src/SchemaPanel.css',
      ]),
    )
    for (const file of cssFiles) {
      // Comments may DISCUSS !important -- layers.css explains why it
      // has none. Only declarations count.
      const withoutComments = read(file).replace(/\/\*[\s\S]*?\*\//g, '')
      expect(withoutComments, file).not.toContain('!important')
    }
  })
})

describe('nothing we write escapes the cascade order', () => {
  /**
   * 09-S1-02, closed the other way round -- MEASURED, not assumed.
   *
   * The audit recorded the layer architecture as declared and never
   * used: six of seven layers empty, every rule unlayered, and a
   * choice between migrating in one pass or deleting the declaration.
   * Its own follow-up already doubted that, which is why the
   * front-end brief says to re-measure before acting.
   *
   * Re-measured against the BUILT bundle: `npm run build`, then a walk
   * over every emitted stylesheet counting top-level rules inside and
   * outside a layer block. ZERO unlayered rules. 2,954 in vendor, 205
   * in components, 2 in tokens. So the half-migrated cascade the
   * finding feared does not exist, and neither prescribed action
   * applies -- there is nothing to migrate, and deleting a
   * declaration that every rule already obeys would create the exact
   * inversion the file above describes.
   *
   * FOUR LAYERS ARE EMPTY AND THAT IS NOT A DEFECT. `overrides` is
   * documented in layers.css as one that SHOULD stay empty;
   * `utilities` has no helper yet; `base` and `layout` hold rules that
   * currently sit fine in `components`. Inventing rules to fill them
   * is the speculative code PRINCIPLES 7 forbids, and splitting
   * existing rules across layers changes the cascade in a way jsdom
   * cannot see.
   *
   * WHAT WAS ACTUALLY MISSING was an assertion. layers.css says
   * plainly that "nothing in this repository can catch that", of an
   * unlayered rule silently beating every layer. That was true. This
   * is the catch, and it is the only part of 09-S1-02 worth building:
   * it pins the property the finding cared about, without the
   * migration the measurement says is unnecessary.
   *
   * SOURCE, NOT BUILD, for the same reason as the tests above -- a
   * unit test cannot run vite. That is a real limit: this proves every
   * rule we AUTHOR is layered, not that the bundler kept it that way.
   * The build was measured by hand at the commit that added this.
   */

  /** Rules in a stylesheet that sit outside every `@layer` block. */
  function unlayeredRules(css: string): string[] {
    const withoutComments = css.replace(/\/\*[\s\S]*?\*\//g, '')
    const found: string[] = []
    let depth = 0
    let layerDepth: number | null = null
    let start = 0

    for (let i = 0; i < withoutComments.length; i += 1) {
      const char = withoutComments[i]
      if (char === '{') {
        const prelude = withoutComments.slice(start, i).trim().replace(/\s+/g, ' ')
        if (/^@layer\b/.test(prelude) && layerDepth === null) {
          layerDepth = depth
        } else if (layerDepth === null && !prelude.startsWith('@')) {
          // A real rule, at no enclosing layer. An at-rule such as
          // @media is not itself a rule; its CONTENTS are checked by
          // the same walk once we descend into them.
          found.push(prelude.slice(0, 60))
        }
        depth += 1
        start = i + 1
      } else if (char === '}') {
        depth -= 1
        if (layerDepth !== null && depth === layerDepth) layerDepth = null
        start = i + 1
      } else if (char === ';') {
        start = i + 1
      }
    }
    return found
  }

  it('finds rules at all, so an empty parse cannot pass', () => {
    // THE CONTROL INSIDE THE TEST. Every assertion below is an
    // absence; a parser that silently matched nothing would report
    // perfect compliance. This proves the walk sees real rules by
    // checking it finds them when the layer wrapper is removed.
    const stripped = read('packages/shell-api/src/index.css').replace(/@layer components \{/, '{')

    expect(unlayeredRules(stripped).length).toBeGreaterThan(50)
  })

  it('puts every rule we author inside a layer', () => {
    const offenders: string[] = []
    for (const sheet of allStylesheets()) {
      // layers.css itself holds only the declaration and the import.
      if (sheet === join('src', 'layers.css')) continue
      for (const rule of unlayeredRules(read(sheet))) offenders.push(`${sheet}: ${rule}`)
    }

    expect(offenders).toEqual([])
  })
})
