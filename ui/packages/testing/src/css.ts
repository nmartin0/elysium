/**
 * Rules a stylesheet authors OUTSIDE every `@layer` block.
 *
 * Unlayered styles beat every layer, so one unlayered rule silently
 * inverts the cascade Elysium relies on (ui/src/layers.css): Blueprint,
 * or a module's rule, would win over everything layered. Moved here from
 * ui/src/layers.test.ts when modules needed the same check of their own
 * stylesheets (the conformance suite's `layered-css`).
 *
 * A walk over braces, not a CSS parser: an at-rule such as `@media` is
 * not itself a rule, and its contents are checked as the walk descends.
 * Comments are removed first.
 */
export function unlayeredRules(css: string): string[] {
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
