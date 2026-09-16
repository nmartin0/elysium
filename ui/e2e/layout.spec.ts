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
// SETUP is the same as shell.spec.ts, which documents it in full: a
// real backend and a real dev server, then `npx playwright test` from
// ui/. Deliberately NOT part of `npm test`, which stays fast and
// mocked.
//
// A NOTE ON PROVENANCE, since it matters for trust: this file was
// written without being run. The container it was authored in cannot
// download a browser -- cdn.playwright.dev is not in its network
// allowlist -- so every assertion here is a claim awaiting its first
// execution. Expect to fix selectors on the first run.

import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

const PLAIN_USER = { username: 'plainuser', password: 'plainpass123' }

async function login(page: Page, user: { username: string; password: string }) {
  await page.goto('/')
  await page.getByLabel(/username/i).fill(user.username)
  await page.getByLabel(/password/i).fill(user.password)
  await page.getByRole('button', { name: /log in/i }).click()
  await expect(page.getByRole('link', { name: /browse/i })).toBeVisible()
}

test.describe('the selection checkbox', () => {
  test.beforeEach(async ({ page }) => {
    await login(page, PLAIN_USER)
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
    const boxes = page.locator('.object-search__select')
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
    await login(page, PLAIN_USER)
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
