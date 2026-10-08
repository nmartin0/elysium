/**
 * Claims the UI roadmap made about the BACKEND, still checked after the
 * roadmap itself is gone.
 *
 * UI_ROADMAP.md was consumed into BLOCKING.md in patch 502, and this
 * file kept reading it -- so the UI suite had a failing test file that
 * nobody saw, because nobody could run the UI suite.
 *
 * WHAT WAS DROPPED: two assertions that the roadmap's PROSE no longer
 * described two solved problems. There is no prose now, so there is
 * nothing to guard; BLOCKING.md has its own guard,
 * tests/unit/test_blocking_is_intact.py.
 *
 * WHAT WAS KEPT, and why it is worth keeping without the document: the
 * backend facts those entries turned on. The migration MECHANISM
 * exists (`add_column_if_missing`), `user_version` is still the real
 * gap, and the logrotate config is real and does not use copytruncate.
 * Each was true when the roadmap was written and each could stop being
 * true; the document going away does not change that.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..', '..')

/** Every .py under core/, api/ and scripts/. */
function backendSource(): { file: string; source: string }[] {
  const found: { file: string; source: string }[] = []
  const walk = (dir: string) => {
    if (!existsSync(dir)) return
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== '__pycache__') walk(full)
      } else if (entry.name.endsWith('.py')) {
        found.push({ file: path.relative(repoRoot, full), source: readFileSync(full, 'utf8') })
      }
    }
  }
  for (const dir of ['core', 'api', 'scripts']) walk(path.join(repoRoot, dir))
  return found
}

describe('claims the UI roadmap made about the backend', () => {
  /**
   * THE PER-TEST OVERRIDE IS GONE, because the cause was general and
   * the fix should have been too.
   *
   * This test failed intermittently in full runs and passed every time
   * in isolation. The timing said why: 6269ms against 17ms and 5ms for
   * its siblings in the same file. It walks `core`, `api` and `scripts`
   * and reads every .py file -- a few hundred synchronous reads --
   * while eighty other test files compete for the same disk. Five
   * seconds is vitest's default, not a budget anybody chose for this.
   *
   * The work is the point: an assertion about what the backend does
   * has to read the backend. Making it cheaper would mean sampling,
   * and a sampled walk cannot support "an empty walk cannot pass".
   *
   * The 30-second budget now set in vite.config.ts covers this and the
   * two tests that failed on the owner's machine for the same reason.
   * Patching one test at a time was treating a property of the SUITE
   * as a property of the test.
   */
  it('reads the backend at all, so an empty walk cannot pass', () => {
    // THE CONTROL INSIDE THE TEST. Every assertion below is over a
    // walk of directories this package does not own; if that walk
    // ever returns nothing -- a move, a rename, a restructure -- the
    // absence checks would pass vacuously and say the opposite of the
    // truth.
    const files = backendSource()

    expect(files.length).toBeGreaterThan(50)
    expect(files.map((f) => f.file)).toContain('core/sqlite_connection.py')
  })

  it('item 22: the migration MECHANISM still exists', () => {
    const defines = backendSource().filter(({ source }) => /def add_column_if_missing\b/.test(source))
    const users = backendSource().filter(({ source }) => /add_column_if_missing\(/.test(source))

    expect(
      defines.length,
      'roadmap item 22 says the mechanism EXISTS and only the version is missing. ' +
        'add_column_if_missing is gone, so re-read item 22 before trusting it.',
    ).toBe(1)
    // Four stores plus its own definition site.
    expect(users.length).toBeGreaterThanOrEqual(4)
  })

  it('item 22: user_version is still the real gap', () => {
    // The one part of the original entry that survived. If a store
    // starts recording a schema version, item 22 is done and should
    // say so rather than sitting in the queue.
    const recording = backendSource().filter(({ source }) => /user_version/.test(source))

    expect(
      recording.map((f) => f.file),
      'roadmap item 22 says no store records a schema version. Something now does, ' +
        'so item 22 is finished and the entry needs closing.',
    ).toEqual([])
  })

  it('item 22: the column its old argument rested on still migrates itself', () => {
    // The specific, checkable refutation: the feared case arrived and
    // the mechanism handled it.
    const auth = readFileSync(path.join(repoRoot, 'core', 'auth', 'database.py'), 'utf8')

    expect(auth).toMatch(/must_change_password/)
    expect(auth).toMatch(/add_column_if_missing\(\s*["']users["']\s*,\s*["']must_change_password["']/)
  })

  it('item 25: log rotation still ships and is still installed', () => {
    const config = path.join(repoRoot, 'deployment', 'logrotate', 'elysium')
    const installer = readFileSync(path.join(repoRoot, 'install', 'install.sh'), 'utf8')

    expect(
      existsSync(config),
      'roadmap item 25 is marked CLOSED because this config exists. It does not, ' + 'so item 25 needs reopening.',
    ).toBe(true)
    expect(installer).toMatch(/logrotate\.d\/elysium/)
    // NOT copytruncate, which would lose records written between the
    // copy and the truncate -- the trade the open-per-append audit
    // log deliberately refused. Item 25's correction says so.
    expect(readFileSync(config, 'utf8')).not.toMatch(/^\s*copytruncate/m)
  })
})
