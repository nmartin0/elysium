// shell.spec.ts -- real, persisted end-to-end coverage of the app
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
//
// REBUILT for the real, current Blueprint-based DOM, not carried
// forward stale -- a real, significant find, not a routine touch-up:
// this whole file's own selectors predated the Blueprint migration
// entirely, and since this suite is deliberately NOT part of `npm
// test`, nothing run this whole migration would ever have caught it
// silently breaking. Three real, confirmed mismatches, all traced
// directly against Shell.tsx/UserMenu.tsx's own real, current output,
// not guessed: (1) `nav.app__nav` can never match anything anymore --
// .app__nav is now a real Blueprint <Menu>, which renders as a <ul>,
// never a <nav> element at all; (2) MenuItem sets role="menuitem"
// explicitly, not the implicit "link" role a bare <a href> would
// otherwise carry, so `getByRole('link', ...)` against a nav item can
// never match either; (3) "Log out" moved inside UserMenu's own real,
// closed-by-default dropdown -- it is not a directly-visible button
// anymore, and has to be opened first.
import { test, expect } from '@playwright/test'

test.describe('shell nav genuinely reflects real permissions', () => {
  test('a plain user (no manage:users) sees only Query and Browse', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('pageerror', (exc) => consoleErrors.push(String(exc)))

    await page.goto('/')
    await expect(page.getByText('Elysium')).toBeVisible()
    await page.getByLabel('Username').fill('plainuser')
    await page.getByLabel('Password').fill('plainpass123')
    await page.getByRole('button', { name: 'Log in' }).click()

    const nav = page.locator('.app__nav')
    await expect(nav.getByRole('menuitem', { name: 'Query' })).toBeVisible()
    await expect(nav.getByRole('menuitem', { name: 'Browse' })).toBeVisible()
    await expect(nav.getByRole('menuitem', { name: 'Admin' })).toHaveCount(0)

    expect(consoleErrors).toEqual([])
  })

  test('an admin user sees Admin too, and it actually works', async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username').fill('adminuser')
    await page.getByLabel('Password').fill('adminpass123')
    await page.getByRole('button', { name: 'Log in' }).click()

    const nav = page.locator('.app__nav')
    await expect(nav.getByRole('menuitem', { name: 'Admin' })).toBeVisible()

    await nav.getByRole('menuitem', { name: 'Admin' }).click()
    await expect(page).toHaveURL(/\/admin$/)
    await expect(page.getByRole('heading', { name: 'Create user' })).toBeVisible()
  })
})

test.describe('real click-through navigation across every sub-app', () => {
  test('Query -> Browse -> a real object detail page, all via real clicks', async ({ page }) => {
    const consoleErrors: string[] = []
    page.on('pageerror', (exc) => consoleErrors.push(String(exc)))

    await page.goto('/')
    await page.getByLabel('Username').fill('plainuser')
    await page.getByLabel('Password').fill('plainpass123')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page).toHaveURL(/\/query$/)

    await page.getByRole('menuitem', { name: 'Browse' }).click()
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
    await expect(page.locator('.app__nav')).toBeVisible()

    // Log out lives inside UserMenu's own real, closed-by-default
    // dropdown now -- opened via its own trigger (a class selector,
    // deliberately, not a name-based role query: the trigger's own
    // accessible name is the real, logged-in username itself once
    // GET /me resolves, which this test does not want to hardcode or
    // otherwise couple itself to).
    await page.locator('.user-menu__trigger').click()
    await page.getByRole('menuitem', { name: 'Log out' }).click()

    await expect(page.getByLabel('Username')).toBeVisible()
    await expect(page.locator('.app__nav')).toHaveCount(0)
  })
})
