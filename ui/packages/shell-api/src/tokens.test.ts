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

import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const read = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8')

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
