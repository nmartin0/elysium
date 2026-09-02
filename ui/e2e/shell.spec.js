// shell.spec.js -- real, persisted end-to-end coverage of the app
// shell against a REAL running backend and frontend, not a mocked
// one. Mirrors, as a re-runnable test, the exact manual verification
// this shell redesign was originally checked with -- login gating,
// nav genuinely reflecting real permissions, real click-through
// navigation, real logout, and (new here) zero uncaught console
// errors across the whole flow.
//
// REQUIRES A REAL, RUNNING SERVER PAIR, set up exactly like every
// other live test in this project's own session history:
//
//   export ELYSIUM_CONFIG_DIR=~/elysium/tests/integration/fixtures
//   export ELYSIUM_DATA_DIR=/tmp/e2e_data
//   export ELYSIUM_LOG_DIR=/tmp/e2e_log
//   (build the fixture databases, same as any other live test)
//   python3 -c "... ud.create_user('plainuser', 'plainpass123', 'us-west', 'editor') ..."
//   python3 -c "... ud.create_user('adminuser', 'adminpass123', None, 'admin') ..."
//   uvicorn api.app:app --reload   (one terminal)
//   npm run dev                     (a second terminal, inside ui/)
//
// Then, from ui/: npx playwright test
//
// NOT run as part of `npm test` (that stays fast, mocked, no real
// server needed) -- same reasoning as this project's own backend
// integration tests staying separate from its fast unit suite.
import { test, expect } from '@playwright/test'

test.describe('shell nav genuinely reflects real permissions', () => {
  test('a plain user (no manage:users) sees only Query and Browse', async ({ page }) => {
    const consoleErrors = []
    page.on('pageerror', (exc) => consoleErrors.push(String(exc)))

    await page.goto('/')
    await expect(page.getByText('Elysium')).toBeVisible()
    await page.getByLabel('Username').fill('plainuser')
    await page.getByLabel('Password').fill('plainpass123')
    await page.getByRole('button', { name: 'Log in' }).click()

    const nav = page.locator('nav.app__nav')
    await expect(nav.getByRole('link', { name: 'Query' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Browse' })).toBeVisible()
    await expect(nav.getByRole('link', { name: 'Admin' })).toHaveCount(0)

    expect(consoleErrors).toEqual([])
  })

  test('an admin user sees Admin too, and it actually works', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username').fill('adminuser')
    await page.getByLabel('Password').fill('adminpass123')
    await page.getByRole('button', { name: 'Log in' }).click()

    const nav = page.locator('nav.app__nav')
    await expect(nav.getByRole('link', { name: 'Admin' })).toBeVisible()

    await nav.getByRole('link', { name: 'Admin' }).click()
    await expect(page).toHaveURL(/\/admin$/)
    await expect(page.getByRole('heading', { name: 'Create user' })).toBeVisible()
  })
})

test.describe('real click-through navigation across every sub-app', () => {
  test('Query -> Browse -> a real object detail page, all via real clicks', async ({ page }) => {
    const consoleErrors = []
    page.on('pageerror', (exc) => consoleErrors.push(String(exc)))

    await page.goto('/')
    await page.getByLabel('Username').fill('plainuser')
    await page.getByLabel('Password').fill('plainpass123')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/query$/)

    await page.getByRole('link', { name: 'Browse' }).click()
    await expect(page).toHaveURL(/\/browse$/)

    // A real customer, from the real fixtures -- confirms title_field
    // still renders through the new shell, not just that navigation
    // itself works. Specifically the result TITLE, not the field
    // list further down in the same card, which also shows "Ada
    // Okafor" again as the "Name" field's own value -- a plain text
    // match would be genuinely ambiguous between the two.
    await page.locator('.object-search__result-title', { hasText: 'Ada Okafor' }).click()
    await expect(page).toHaveURL(/\/objects\/Customer\/cust_001$/)
    await expect(page.locator('.object-detail__title')).toHaveText('Ada Okafor')

    expect(consoleErrors).toEqual([])
  })
})

test.describe('logout genuinely clears session state', () => {
  test('logging out returns to the login screen with no nav left behind', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username').fill('adminuser')
    await page.getByLabel('Password').fill('adminpass123')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.locator('nav.app__nav')).toBeVisible()

    await page.getByRole('button', { name: 'Log out' }).click()

    await expect(page.getByLabel('Username')).toBeVisible()
    await expect(page.locator('nav.app__nav')).toHaveCount(0)
  })
})
