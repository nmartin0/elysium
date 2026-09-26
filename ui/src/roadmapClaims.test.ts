/**
 * UI_ROADMAP.md makes claims about code it does not live next to.
 *
 * E-19: two entries described gaps that were filled. Item 25 said the
 * audit log sat "in a directory with no rotation" -- there is a
 * logrotate config, installed by install/install.sh. Item 22 said
 * there was "no migration mechanism on ANY store" and built its whole
 * urgency on a `must_change_password` column that nothing could add --
 * that column ships, and the line that adds it to an existing table is
 * twelve lines below it in the same file.
 *
 * WHY A TEST FOR PROSE ABOUT ANOTHER DIRECTORY. Both entries were true
 * when written. A roadmap decays precisely because nothing executes
 * it, and a roadmap that describes solved problems is worse than no
 * roadmap -- someone schedules the work, or argues an ordering, from
 * a state of the world that has passed. That is exactly what the
 * "ordering note that overrides difficulty" was doing.
 *
 * SO THIS PINS THE THREE FACTS THE CORRECTED ENTRIES REST ON. If the
 * backend changes any of them, the entry needs rewriting again -- and
 * this is the thing that will say so. A failure here is NOT a broken
 * front end: the message says which entry to re-read, because a test
 * that fails confusingly across an ownership boundary teaches people
 * to skip it.
 */

import { existsSync, readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..', '..')
const ROADMAP = readFileSync(path.join(repoRoot, 'UI_ROADMAP.md'), 'utf8')

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

describe("UI_ROADMAP's claims about the backend", () => {
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
      'UI_ROADMAP item 22 says the mechanism EXISTS and only the version is missing. ' +
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
      'UI_ROADMAP item 22 says no store records a schema version. Something now does, ' +
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
      'UI_ROADMAP item 25 is marked CLOSED because this config exists. It does not, ' + 'so item 25 needs reopening.',
    ).toBe(true)
    expect(installer).toMatch(/logrotate\.d\/elysium/)
    // NOT copytruncate, which would lose records written between the
    // copy and the truncate -- the trade the open-per-append audit
    // log deliberately refused. Item 25's correction says so.
    expect(readFileSync(config, 'utf8')).not.toMatch(/^\s*copytruncate/m)
  })

  it('does not still describe the two gaps as open', () => {
    // Guards the correction itself: if either entry is reverted to
    // its old wording, this fails.
    expect(ROADMAP).not.toMatch(/no migration mechanism on ANY store\s*--\s*\n?user_directory/)
    expect(ROADMAP).not.toMatch(
      /\*\*25\. Log rotation\.\*\* An audit entry per field access, in a directory\nwith no rotation/,
    )
  })
})
