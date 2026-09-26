// layout.spec.ts -- what a jsdom test cannot see.
//
// WHY THIS FILE EXISTS. Six attempts at one checkbox in a single
// session, none caught by 786 passing unit tests, every one found by a
// person clicking. The common factor: jsdom computes NO LAYOUT. It has
// no stacking contexts, no hit-testing, no cascade resolution, and no
// idea whether one element covers another.
//
// So every fix for a visual fault was verified by reasoning rather
// than observation, and reasoning was wrong five times.
//
// WHAT BELONGS HERE: assertions about COMPUTED STYLE and REAL CLICKS.
// Not "the component renders a checkbox" -- a unit test does that
// faster and in more detail. This file is for facts only a browser
// knows.
//
// SETUP, EVERY LINE FROM THE REPOSITORY ROOT:
//
//   cd ~/elysium/ui && npm run build   (tests the BUILT bundle)
//   cd ~/elysium && python -m scripts.create_e2e_users \
//                       --yes-this-is-development
//   cd ~/elysium && uvicorn api.app:app  (leave a running one alone)
//   cd ~/elysium/ui && npm run e2e
//
// No dev server. uvicorn serves both, so the only process needed is
// the one already running.
//
// Deliberately NOT part of `npm test`, which stays fast and mocked.
//
// A NOTE ON PROVENANCE, since it matters for trust: this file was
// written in a container that cannot download a browser
// (cdn.playwright.dev is not in its network allowlist), so it is
// authored blind and its assertions have never been seen to pass.
//
// Their first run failed eleven for eleven with
// ERR_CONNECTION_REFUSED -- no server on the port the config named --
// which proved only that the config was wrong. That is fixed here;
// the assertions themselves remain unverified, and selectors may
// still need correcting.

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// THE DEVELOPMENT USER scripts/create_debug_user.py creates, so these
// run against the deployment a developer already has rather than
// needing fixture users made first. shell.spec.ts predates that script
// and still builds its own; worth reconciling, not worth blocking on.
const DEV_USER = { username: 'debug', password: 'a' }

async function login(page: Page, user: { username: string; password: string }) {
  await page.goto('/')
  await page.getByLabel(/username/i).fill(user.username)
  await page.getByLabel(/password/i).fill(user.password)
  await page.getByRole('button', { name: /log in/i }).click()

  // FAIL ON THE LOGIN, NOT ON SOMETHING DOWNSTREAM. A first version
  // waited for a nav item, so a failed login and a wrong selector
  // produced the identical message -- and both were happening at once,
  // which cost a whole run to untangle.
  //
  // The nav is a Blueprint Menu, so its items are role="menuitem", not
  // role="link". That was the wrong selector.
  await expect(
    page.locator('.app__nav'),
    'login did not complete -- does this user exist on the server under test?',
  ).toBeVisible()
  await expect(page.getByRole('menuitem', { name: /browse/i })).toBeVisible()
}

test.describe('the selection checkbox', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, DEV_USER)
    await page.goto('/browse?type=Customer')
    await expect(page.locator('.object-search__result').first()).toBeVisible()
  })

  test('a click selects rather than navigating', async ({ page }) => {
    // THE FAULT THIS WOULD HAVE CAUGHT FIRST. The card used to stretch
    // its link across its whole surface, so a click meant for the
    // checkbox navigated instead. Only a server log revealed it.
    const before = page.url()
    await page.locator('.object-search__select').first().click()

    expect(page.url()).toBe(before)
    await expect(page.getByText(/1 selected/)).toBeVisible()
  })

  test('every click toggles, with none swallowed', async ({ page }) => {
    // A timing-based dedupe once made clicks intermittently do
    // nothing: a real click landing inside a 50ms window was mistaken
    // for a browser-forwarded one. Ten clicks is enough to expose a
    // window; a unit test in one React batch is not.
    const box = page.locator('.object-search__select').first()

    for (let click = 0; click < 10; click += 1) {
      await box.click()
      await expect(box).toBeChecked({ checked: click % 2 === 0 })
    }
  })

  test('shift-click selects the range between', async ({ page }) => {
    // Mozilla #559506 suppresses the change event when a LABEL is
    // shift-clicked, which is why this worked in no browser while
    // passing in jsdom.
    // TRANSACTION, NOT CUSTOMER. A range needs at least three rows and
    // the fixture has two customers, so nth(2) waited thirty seconds
    // for a row that does not exist -- my arithmetic, not a fault.
    await page.goto('/browse?type=Transaction')
    const boxes = page.locator('.object-search__select')
    await expect(boxes.nth(2)).toBeVisible()

    await boxes.nth(0).click()
    await boxes.nth(2).click({ modifiers: ['Shift'] })

    await expect(page.getByText(/3 selected/)).toBeVisible()
  })

  test('it sits beside its row, not above it', async ({ page }) => {
    /** COMPUTED GEOMETRY, which is the whole point of this file.
     *
     * A bare `label { flex-direction: column }` stacked every checkbox
     * above its own text, app-wide. jsdom cannot see that: it computes
     * no layout, so the rule applied and nothing observed it.
     */
    const box = page.locator('.object-search__select').first()
    const title = page.locator('.object-search__result-title').first()

    const boxBox = await box.boundingBox()
    const titleBox = await title.boundingBox()

    expect(boxBox).not.toBeNull()
    expect(titleBox).not.toBeNull()
    // Beside: the checkbox ends before the title begins, and they
    // overlap vertically.
    expect(boxBox!.x + boxBox!.width).toBeLessThanOrEqual(titleBox!.x + 1)
    expect(boxBox!.y).toBeLessThan(titleBox!.y + titleBox!.height)
  })

  test('nothing covers it', async ({ page }) => {
    // HIT-TESTING, which jsdom has none of. Playwright refuses to
    // click an element obscured by another, so this fails loudly if a
    // stretched link or overlay ever returns.
    await page.locator('.object-search__select').first().click({ timeout: 2000 })

    await expect(page.getByText(/1 selected/)).toBeVisible()
  })
})

test.describe('Blueprint controls keep their own layout', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, DEV_USER)
    await page.goto('/browse?type=Customer')
    await expect(page.locator('.object-search__result').first()).toBeVisible()
  })

  test('a Columns checkbox sits on one line with its label', async ({ page }) => {
    /** THE SAME FAULT IN ANOTHER PLACE, and the reason it took so long
     * to find: it was in shared CSS, so searching components for
     * `<Checkbox` found nothing.
     *
     * Our stylesheets are UNLAYERED while Blueprint sits in a `vendor`
     * layer, so any bare element selector we write outranks Blueprint
     * regardless of specificity. `label` beats `.bp6-control`.
     */
    const control = page.locator('.workspace__filter .bp6-control').first()

    const direction = await control.evaluate((element) => getComputedStyle(element).flexDirection)

    expect(direction).not.toBe('column')
  })

  test('its indicator and text share a line', async ({ page }) => {
    const control = page.locator('.workspace__filter .bp6-control').first()
    const height = (await control.boundingBox())!.height

    // One line, not two. A stacked control is roughly twice as tall.
    expect(height).toBeLessThan(40)
  })
})

// THE CHECKBOXES ADDED SINCE THE SWEEP. BACKLOG item 2.4 asked "which
// other screens show the checkbox-above-the-row problem"; the sweep
// found two Checkbox elements, and patches 280 and 286 have added more
// -- the Watch dialog's recipients and the Roles screen's grants.
//
// AUTHORED BLIND, like the rest of this file: written in a container
// that cannot download a browser. The measurements are the two above,
// reused rather than reinvented.
//
// FIRST REAL RUN: the Roles check passed as written. The Watch check
// failed in its STEPS, not its measurement -- see the comment in it.
//
// THE WATCH CHECK SAVES A VIEW named "e2e layout check" in the
// deployment it runs against. Saving the same name REPLACES it, so
// repeated runs leave one, not many.

test.describe('the checkboxes added since the sweep', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, DEV_USER)
  })

  test('a Roles grant sits on one line with its label', async ({ page }) => {
    /** DEV_USER holds manage:roles in the shipped policy.yaml, so the
     *  Roles screen loads rather than refusing. */
    await page.goto('/admin')
    await page.getByRole('button', { name: 'Roles' }).click()
    await page.getByLabel('Role to change').selectOption('customer_service')

    const control = page.locator('.roles__group .bp6-control').first()
    await expect(control).toBeVisible()

    expect(await control.evaluate((element) => getComputedStyle(element).flexDirection)).not.toBe('column')
    expect((await control.boundingBox())!.height).toBeLessThan(40)
  })

  test('a Watch recipient sits on one line with its label', async ({ page }) => {
    await page.goto('/browse?type=Customer')

    // OPEN THE POPOVER BY EITHER LABEL, because this test's own saved
    // view changes it.
    //
    // NOT IDEMPOTENT UNTIL THIS. The trigger reads "Saved views" until
    // the current URL matches a saved view, and then takes that view's
    // NAME -- which the comment below already explains, for the save.
    // The same thing is true on ARRIVAL: once this test has run once,
    // its own view matches /browse?type=Customer, so the second run
    // found no "Saved views" button and timed out. It passed alone and
    // failed in a full run for that reason, which is the signature of
    // a test leaving state behind rather than a real defect.
    const popover = page.getByRole('button', { name: /saved views|e2e layout check/i }).first()
    await popover.click()
    await page.getByPlaceholder(/name this view/i).fill('e2e layout check')
    await page.getByRole('button', { name: /^(save|update)$/i }).click()

    // WAIT FOR THE SAVE, by the one thing that proves it finished: the
    // popover's button takes the SAVED VIEW'S NAME once the current URL
    // matches a saved view. Saving also closes the popover.
    //
    // THE FIRST RUN FAILED HERE. It clicked /saved views/i straight
    // after Save -- a label that exists only BEFORE the save completes
    // -- so the click raced the save, and the Watch button was never
    // on screen. Its first real run is how that was found.
    //
    // EXACT, because names match as substrings by default and
    // "e2e layout check" is inside "Watch e2e layout check".
    const trigger = page.getByRole('button', { name: 'e2e layout check', exact: true })
    await expect(trigger).toBeVisible()
    await trigger.click()
    await page.getByRole('button', { name: 'Watch e2e layout check' }).click()

    const control = page.locator('.bp6-dialog .bp6-control').first()
    await expect(control).toBeVisible()

    expect(await control.evaluate((element) => getComputedStyle(element).flexDirection)).not.toBe('column')
    expect((await control.boundingBox())!.height).toBeLessThan(40)

    // PUT THE DEPLOYMENT BACK. A saved view is real, persisted data on
    // whatever server this ran against -- not a fixture that vanishes
    // with the browser. Leaving it behind is what made the run above
    // depend on whether this test had ever run before, and on a shared
    // dev server it accumulates one stray view per run forever.
    await page.keyboard.press('Escape')
    await page.getByRole('button', { name: 'e2e layout check', exact: true }).click()
    await page.getByRole('button', { name: 'Forget e2e layout check' }).click()
    await expect(page.getByRole('button', { name: 'e2e layout check', exact: true })).toBeHidden()
  })
})
