/**
 * No panel rebuilds its loader because the shell re-rendered.
 *
 * THE BUG, MEASURED. App.tsx declares handleSessionExpired as a plain
 * function inside the component, so it is a new identity on every
 * render. Seven panels listed it as a dependency -- five on a `load`
 * useCallback run from useEffect([load]), two on the effect itself --
 * so every render of the shell rebuilt the loader and refired the
 * effect. ApprovalsPanel before the fix: three parent renders, three
 * fetches. After: one.
 *
 * MirrorPanel was worse, because its effect also owns a 30-second
 * poll: the interval was cleared and recreated on every parent
 * render, so a shell rendering faster than every 30 seconds meant the
 * timer never reached its deadline and the "polling" dashboard was
 * only ever refreshed by accident.
 *
 * WHY A SOURCE CHECK RATHER THAN SEVEN BEHAVIOURAL TESTS. It found
 * two sites the linter did not. react/set-state-in-effect flagged
 * five of these panels and missed MetricsPanel and MirrorPanel
 * entirely, because those call the API inline in the effect rather
 * than through a useCallback. The lint rule and this check disagree
 * about which files are interesting, and this one is aimed at the
 * actual defect: depending on a callback the parent recreates.
 *
 * Behavioural tests exist too, in the panels' own files, for the two
 * where the consequence is most specific.
 */

import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const packagesRoot = path.resolve(here, '..', 'packages')

function panelSources(): { file: string; source: string }[] {
  const found: { file: string; source: string }[] = []
  for (const pkg of readdirSync(packagesRoot)) {
    const src = path.join(packagesRoot, pkg, 'src')
    for (const entry of readdirSync(src, { withFileTypes: true })) {
      if (!entry.isFile() || !entry.name.endsWith('.tsx') || entry.name.includes('.test.')) continue
      found.push({ file: `${pkg}/${entry.name}`, source: readFileSync(path.join(src, entry.name), 'utf8') })
    }
  }
  return found
}

describe('the shell re-rendering does not restart a panel', () => {
  it('finds the panels, so an empty walk cannot pass', () => {
    // THE CONTROL INSIDE THE TEST: the assertion below is an absence.
    const panels = panelSources()

    expect(panels.length).toBeGreaterThan(20)
    expect(panels.map((p) => p.file)).toContain('app-approvals/ApprovalsPanel.tsx')
  })

  it('never depends on onSessionExpired in a hook dependency array', () => {
    // The shape IS the bug: a loader or an effect that restarts
    // because the parent handed down a fresh arrow.
    const offenders = panelSources()
      .filter(({ source }) => /\}, \[\s*onSessionExpired\s*\]\)/.test(source))
      .map(({ file }) => file)

    expect(offenders).toEqual([])
  })

  it('reads the callback through a ref written in an effect', () => {
    // The replacement, checked positively rather than inferred from
    // the absence above -- and a ref WRITTEN DURING RENDER would
    // satisfy the absence while breaking react/refs, which is enforced
    // but only as a lint rule on these files.
    for (const { file, source } of panelSources()) {
      if (!source.includes('latestSessionExpired')) continue

      expect(source, `${file} must write the ref in an effect, not during render`).toMatch(
        /useEffect\(\(\) => \{\s*latestSessionExpired\.current = onSessionExpired\s*\}\)/,
      )
    }
  })
})
