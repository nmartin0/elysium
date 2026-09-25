/**
 * ui/README.md describes the thing it sits in -- checked, not trusted.
 *
 * 10-S1-01..04. Four documentation defects in one file, and the file
 * is the FIRST thing a new contributor reads: it said the UI had "no
 * design system" while being built on Blueprint, named four of seven
 * packages, enumerated four of shell-api's twenty-three modules and
 * two of app-browse's fourteen components, and claimed "five separate
 * checks" two lines above "all four run".
 *
 * WHY A TEST AND NOT JUST AN EDIT. Every one of those was true when
 * written. Prose about a codebase decays silently because nothing
 * executes it, so correcting the words without pinning them buys
 * exactly one accurate day. These assertions are the cheapest part of
 * the fix and the only part that lasts.
 *
 * WHAT IS DELIBERATELY NOT ASSERTED: the per-package descriptions.
 * Pinning prose to a module list is what produced 10-S1-03 -- a
 * snapshot that rots. The README now describes what each package is
 * FOR, and this file pins the package SET, which is a fact with one
 * right answer.
 */

import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiRoot = path.resolve(here, '..')
const README = readFileSync(path.join(uiRoot, 'README.md'), 'utf8')
const PACKAGE_JSON = JSON.parse(readFileSync(path.join(uiRoot, 'package.json'), 'utf8')) as {
  scripts: Record<string, string>
  dependencies: Record<string, string>
}

describe('ui/README.md matches the workspace', () => {
  it('names every package that exists', () => {
    // 10-S1-02. app-schema was missing from this listing for the THIRD
    // time when the audit found it; app-approvals and app-notifications
    // were missing too, which the audit did not say.
    const onDisk = readdirSync(path.join(uiRoot, 'packages'), { withFileTypes: true })
      .filter((entry) => entry.isDirectory())
      .map((entry) => entry.name)
      .sort()

    // THE CONTROL INSIDE THE TEST: an empty read would pass vacuously.
    expect(onDisk.length).toBeGreaterThan(5)
    expect(onDisk).toContain('shell-api')

    const missing = onDisk.filter((pkg) => !README.includes(`ui/packages/${pkg}`))

    expect(missing).toEqual([])
  })

  it('describes no package that does not exist', () => {
    // The opposite direction, which the audit did not ask for. A
    // package removed and left in the listing sends a reader to a
    // directory that is not there -- the same defect pointing the
    // other way, and a guard that only fires one way is half a guard.
    const onDisk = new Set(
      readdirSync(path.join(uiRoot, 'packages'), { withFileTypes: true })
        .filter((entry) => entry.isDirectory())
        .map((entry) => entry.name),
    )
    const named = [...README.matchAll(/ui\/packages\/([a-z0-9-]+)/g)].map((m) => m[1] ?? '')

    expect(named.length).toBeGreaterThan(0)
    expect(named.filter((pkg) => !onDisk.has(pkg))).toEqual([])
  })

  it('does not deny the design system it depends on', () => {
    // 10-S1-01. Blueprint IS the design system, and the standing rule
    // is that it wins over anything we would write ourselves. A README
    // telling a contributor there is none invites exactly the
    // hand-rolled override that rule exists to prevent.
    //
    // A BRIGHT LINE, NOT A JUDGEMENT, and it caught the fix for its own
    // finding: the correction paragraph first QUOTED the old phrase
    // while disowning it, and this failed. A test cannot tell a claim
    // from a quotation of a claim, and the version that tried would be
    // guessing. So the phrase may not appear at all, and the history
    // is recorded in words that describe it instead -- which costs one
    // sentence and leaves nothing to argue about later.
    expect(PACKAGE_JSON.dependencies).toHaveProperty('@blueprintjs/core')
    expect(README).not.toMatch(/no design system/i)
    expect(README).toMatch(/Blueprint/)
  })

  it('states the same number of gate checks the gate actually runs', () => {
    // 10-S1-04. "Five separate ... checks", four listed, "all four
    // run" -- three claims, two numbers, in one paragraph. Read the
    // real script rather than the prose beside it.
    const lint = PACKAGE_JSON.scripts.lint ?? ''
    const steps = lint
      .split('&&')
      .map((step) => step.trim())
      .filter(Boolean)

    const words: Record<string, number> = { ONE: 1, TWO: 2, THREE: 3, FOUR: 4, FIVE: 5, SIX: 6 }
    const claimed = /\b(ONE|TWO|THREE|FOUR|FIVE|SIX)\b checks make up the gate/i.exec(README)?.[1]

    expect(claimed, 'README must state the gate size in words').toBeDefined()
    expect(words[(claimed ?? '').toUpperCase()]).toBe(steps.length)

    // AND EACH TOOL BY NAME, so the number cannot stay right while the
    // list drifts -- which is the shape the original defect had.
    for (const tool of ['oxlint', 'tsc', 'oxfmt', 'knip']) {
      expect(README, `README should name ${tool}`).toContain(tool)
    }
  })
})
