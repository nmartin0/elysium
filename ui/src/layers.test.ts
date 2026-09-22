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
