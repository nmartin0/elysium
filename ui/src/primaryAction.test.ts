import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiRoot = path.resolve(here, '..')

function sourceFiles(): { file: string; source: string }[] {
  const found: { file: string; source: string }[] = []
  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'dist') walk(full)
      } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
        found.push({ file: path.relative(uiRoot, full), source: readFileSync(full, 'utf8') })
      }
    }
  }
  walk(path.join(uiRoot, 'src'))
  walk(path.join(uiRoot, 'packages'))
  return found
}

/**
 * A form's submit button IS its primary action -- the form has already
 * decided which one that is.
 *
 * All three in the application rendered with no intent at all, which
 * Blueprint draws as a default grey control: indistinguishable from a
 * secondary action, and on the Query screen indistinguishable from a
 * disabled one. "Ask" is the single thing Elysium exists to do and it
 * looked like something you could not press.
 *
 * The convention is explicit in the sources -- one clear primary
 * action per screen state, filled accent for primary, outlined or text
 * for secondary.
 */

describe('one primary action per form', () => {
  it('every submit button says it is the primary action', () => {
    const offenders: string[] = []
    for (const { file, source } of sourceFiles()) {
      for (const match of source.matchAll(/<Button\s+type="submit"[^>]*/g)) {
        if (!match[0].includes('intent=')) offenders.push(file)
      }
    }

    expect(offenders).toEqual([])
  })

  it('no file declares two primary submits', () => {
    /** Two primary actions in one view means neither is. */
    const offenders: string[] = []
    for (const { file, source } of sourceFiles()) {
      const primaries = [...source.matchAll(/<Button\s+type="submit"[^>]*intent="primary"/g)]
      if (primaries.length > 1) offenders.push(`${file} (${primaries.length})`)
    }

    expect(offenders).toEqual([])
  })

  it('finds the submit buttons at all, so an empty walk cannot pass', () => {
    /** Every assertion above is over a walk; if it ever returns nothing
     *  -- a move, a rename -- both would pass vacuously and say the
     *  opposite of the truth. */
    const submits = sourceFiles().flatMap(({ source }) => [...source.matchAll(/<Button\s+type="submit"/g)])

    expect(submits.length).toBeGreaterThanOrEqual(3)
  })
})
