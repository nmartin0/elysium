/**
 * Every component that can be told the session expired must actually
 * tell someone.
 *
 * F-31 was filed as one file: ObjectNotes' save path did not call
 * handleIfSessionExpired. Auditing the other call sites found a second
 * and worse one -- ExploreRelated tested
 * `getErrorMessage(caught).includes('401')`, which READ as handled and
 * could never fire, because api/auth_dependency.py answers an expired
 * session with "Invalid or expired session", a sentence containing no
 * digits. The same mistake is rarely alone, and a per-file fix would
 * have left the next one to be found the same slow way.
 *
 * SO THIS CHECKS THE RULE, NOT THE TWO INSTANCES: a 401 is recognised
 * by STATUS, never by searching a human-readable message for a number.
 * A message is written for a person and can be reworded at any time;
 * a status is the contract.
 */

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
  walk(path.join(uiRoot, 'packages'))
  walk(path.join(uiRoot, 'src'))
  return found
}

/**
 * Files that receive onSessionExpired and handle it by some route
 * other than handleIfSessionExpired, each with the reason.
 *
 * AN ALLOWLIST WITH REASONS, not a pattern loose enough to let them
 * through unnoticed: a new file has to be added here deliberately,
 * which is the point at which somebody has to justify it.
 */
const HANDLED_ANOTHER_WAY: Record<string, string> = {
  'packages/app-query/src/QueryPanel.tsx':
    'query() returns a raw Response rather than throwing, so this reads response.status === 401 directly. Checked by status, which is the rule.',
  'packages/app-schema/src/SchemaPanel.tsx':
    'One .catch(() => {}) on a cache warm-up whose result is never displayed. A failure here has no user-visible effect and the real fetch that follows reports its own.',
}

describe('an expired session is recognised by status', () => {
  it('finds the source to check, so an empty walk cannot pass', () => {
    // THE CONTROL INSIDE THE TEST: a moved directory would leave this
    // asserting over nothing.
    const files = sourceFiles()

    expect(files.length).toBeGreaterThan(40)
    expect(files.map((f) => f.file)).toContain('packages/app-browse/src/ObjectNotes.tsx')
  })

  it('never decides a session expired by reading a message', () => {
    // The specific shape ExploreRelated had, and any relative of it:
    // testing the human-readable text for a status code.
    const offenders = sourceFiles()
      .filter(({ source }) => /(?:getErrorMessage|\.message)[^\n]*\.includes\(\s*['"`]\d{3}/.test(source))
      .map(({ file }) => file)

    expect(offenders).toEqual([])
  })

  it('routes a caught failure to onSessionExpired wherever it can', () => {
    const unhandled: string[] = []
    for (const { file, source } of sourceFiles()) {
      if (!source.includes('onSessionExpired')) continue
      if (!/\bcatch\b/.test(source)) continue
      if (source.includes('handleIfSessionExpired')) continue
      if (file in HANDLED_ANOTHER_WAY) continue
      unhandled.push(file)
    }

    expect(unhandled).toEqual([])
  })

  it('keeps the allowlist honest about files that still exist', () => {
    // An allowlist entry for a deleted or since-fixed file is a hole
    // held open for a case that no longer exists -- the same defect
    // the colour-literal exemptions had in 09-S2-01.
    const present = new Set(sourceFiles().map(({ file }) => file))

    for (const file of Object.keys(HANDLED_ANOTHER_WAY)) {
      expect(present.has(file), `${file} is allowlisted but does not exist`).toBe(true)
    }
  })
})
