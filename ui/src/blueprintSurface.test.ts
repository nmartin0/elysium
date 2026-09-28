/**
 * How much of Blueprint this project actually depends on.
 *
 * CONFIG_ROUND_TRIP_AND_UI_KIT.md Part 2 rests on one measurement:
 * "the coupling is shallow -- 49 import sites, 22 distinct
 * components ... Most of what Blueprint provides here is a button with
 * a class name." That is the argument for owning a small kit instead
 * of swapping to a bigger vendor, and it is only true while it stays
 * true.
 *
 * IT DID NOT. Re-measured a fortnight later: 46 sites but THIRTY-TWO
 * components. Ten had been added, and nothing noticed, because nothing
 * was looking. Two of the ten are worse than widgets -- `Classes` is
 * Blueprint's CSS class constants, a deeper coupling than a component,
 * and `OverlaysProvider` is app-level infrastructure in Shell.tsx.
 * Neither is "a button with a class name".
 *
 * WHY A PIN RATHER THAN THE LINT RULE THE PLAN ASKS FOR. Step 4 of the
 * migration is a rule refusing new @blueprintjs imports; applied today
 * it would fail against all 48 existing sites, so it cannot go in
 * until the migration is done. This does the part that is useful NOW:
 * existing use is untouched, and GROWTH becomes a deliberate act with
 * a diff someone has to justify.
 *
 * ADDING ONE IS NOT FORBIDDEN. It is a decision. Add the name below
 * and say in the commit why the kit should own one more thing -- which
 * is the conversation that did not happen ten times.
 */

import { readFileSync, readdirSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const here = path.dirname(fileURLToPath(import.meta.url))
const uiRoot = path.resolve(here, '..')

/**
 * The Blueprint surface as of the UI-KIT re-measurement.
 *
 * Grouped as the migration plan groups them, because the two halves
 * have different answers: the simple ones become ours outright, the
 * behavioural ones get a vendored headless primitive, since focus
 * trapping and ARIA wiring are where a mistake is invisible until a
 * keyboard user hits it.
 */
const PINNED = [
  // Markup and CSS -- the plan's "ours to keep, nobody can abandon them".
  'Button',
  'ButtonGroup',
  'Callout',
  'Card',
  'CardList',
  'FormGroup',
  'H5',
  'HTMLSelect',
  'HTMLTable',
  'Icon',
  'IconName',
  'IconNames',
  'InputGroup',
  'NonIdealState',
  'NumericInput',
  'Spinner',
  'Tag',
  'TextArea',
  // Behaviour -- the six the plan vendors rather than writes.
  'Alert',
  'Checkbox',
  'Dialog',
  'DialogBody',
  'DialogFooter',
  'Menu',
  'MenuDivider',
  'MenuItem',
  'Popover',
  'PopoverNext',
  'OverlaysProvider',
  'Switch',
  'Tab',
  'Tabs',
  // NOT A COMPONENT. Blueprint's CSS class constants, used in
  // Shell.tsx. A deeper coupling than any widget here: it reaches past
  // the component boundary into the library's stylesheet, and owning
  // the kit means owning these names too.
  'Classes',
].sort()

/** Every Blueprint identifier imported by production code. */
function importedSurface(): { components: string[]; sites: number } {
  const components = new Set<string>()
  let sites = 0
  const pattern = /import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*'@blueprintjs\/[^']*'/g

  const walk = (dir: string) => {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name)
      if (entry.isDirectory()) {
        if (entry.name !== 'node_modules' && entry.name !== 'dist') walk(full)
      } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
        // TESTS EXCLUDED: a test importing Blueprint to build a fixture
        // is not the product depending on it, and counting those would
        // make the number move for reasons the migration does not care
        // about.
        for (const match of readFileSync(full, 'utf8').matchAll(pattern)) {
          sites += 1
          for (const raw of (match[1] ?? '').split(',')) {
            const name = raw
              .trim()
              .replace(/^type\s+/, '')
              .split(' as ')[0]
              ?.trim()
            if (name) components.add(name)
          }
        }
      }
    }
  }
  walk(path.join(uiRoot, 'packages'))
  walk(path.join(uiRoot, 'src'))
  return { components: [...components].sort(), sites }
}

describe('the Blueprint surface the UI-KIT plan is measured against', () => {
  it('finds the imports at all, so an empty walk cannot pass', () => {
    // THE CONTROL INSIDE THE TEST: the assertion below is an equality
    // against a list, and an empty read would make it a loud failure
    // rather than a silent pass -- but a read that found only ONE file
    // would not. This pins the floor.
    const { components, sites } = importedSurface()

    expect(sites).toBeGreaterThan(30)
    expect(components).toContain('Button')
  })

  it('imports nothing from Blueprint that is not on the list', () => {
    const added = importedSurface().components.filter((name) => !PINNED.includes(name))

    expect(
      added,
      'A new Blueprint component widens the coupling the UI-KIT plan is built on. ' +
        'Add it to PINNED and say in the commit why the kit should own one more thing.',
    ).toEqual([])
  })

  it('keeps no name on the list that nothing imports', () => {
    // The other direction, and it is what makes the list worth
    // trusting: an entry for a component nobody uses inflates the
    // measured coupling and would quietly excuse a real addition. The
    // same defect the colour-literal exemptions had -- a hole held
    // open for a case that no longer exists.
    const { components } = importedSurface()
    const stale = PINNED.filter((name) => !components.includes(name))

    expect(stale, 'These are pinned but no longer imported. Remove them.').toEqual([])
  })
})
