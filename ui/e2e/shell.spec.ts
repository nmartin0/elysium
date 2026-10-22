// shell.spec.ts -- real, persisted end-to-end coverage of the app
// shell against a REAL running backend and frontend, not a mocked
// one. Mirrors, as a re-runnable test, the exact manual verification
// this shell redesign was originally checked with -- login gating,
// nav genuinely reflecting real permissions, real click-through
// navigation, real logout, and (new here) zero uncaught console
// errors across the whole flow.
//
// SETUP. The steps that used to be here could not work: they named a
// role, `editor`, that this deployment does not define, and asked for
// a separate dev server the tests no longer point at. Nobody noticed,
// because nothing ran them.
//
// EVERY LINE FROM THE REPOSITORY ROOT, spelled out -- a list mixing
// `cd ui && ...` with root-relative commands leaves a reader in ui/
// and produces "No module named 'scripts'".
//
//   cd ~/elysium/ui && npm run build   (tests the BUILT bundle)
//   cd ~/elysium && python -m scripts.create_e2e_users \
//                       --yes-this-is-development
//   cd ~/elysium && uvicorn api.app:app
//   cd ~/elysium/ui && npm run e2e
//
// NO DEV SERVER: uvicorn serves the UI and the API together.
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

test.describe('one Inbox, three tabs (decided 14 Oct)', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.getByLabel('Username').fill('plainuser')
    await page.getByLabel('Password').fill('plainpass123')
    await page.getByRole('button', { name: 'Log in' }).click()
    await expect(page.locator('.app__nav')).toBeVisible()
  })

  test('the rail has one Inbox entry, not three', async ({ page }) => {
    const nav = page.locator('.app__nav')

    // ^Inbox: with something waiting its name goes on ", 3 waiting".
    await expect(nav.getByRole('menuitem', { name: /^Inbox/ })).toBeVisible()
    await expect(nav.getByRole('menuitem', { name: 'Approvals' })).toHaveCount(0)
    await expect(nav.getByRole('menuitem', { name: 'Notifications' })).toHaveCount(0)
  })

  test('an old link lands on its tab', async ({ page }) => {
    // A bookmark or a message from before the Inbox still works.
    await page.goto('/notifications')

    await expect(page).toHaveURL(/\/inbox\?tab=notifications$/)
    await expect(page.getByRole('tab', { name: /Notifications/ })).toHaveAttribute('aria-selected', 'true')
  })

  // THE COUNT IS A BADGE ON THE INBOX'S RAIL ENTRY (step 1.3c; the owner
  // chose the rail as its only place). The counts are stubbed so the
  // badge is certain to be there, and what is checked is what jsdom
  // cannot see: that it is drawn, on top, inside the rail -- open and
  // collapsed, where the rail clips whatever overflows it.
  test('how much is waiting is on the rail, on any screen, and is not clipped', async ({ page }) => {
    await page.route('**/api/me/inbox', (route) =>
      route.fulfill({ json: { approvals: 3, notifications: 0, identity: 0 } }),
    )
    await page.goto('/browse')
    const inbox = page.locator('.app__nav').getByRole('menuitem', { name: 'Inbox, 3 waiting' })
    const badge = inbox.locator('.app__nav-badge')
    await expect(badge).toHaveText('3')

    for (const state of ['open', 'collapsed']) {
      if (state === 'collapsed') {
        await page.keyboard.press('Control+b')
        await expect(page.locator('.app-frame--sidebar-collapsed')).toHaveCount(1)
      }
      await expect(badge, `badge visible with the rail ${state}`).toBeVisible()
      // Nothing covers it, and the rail does not clip it: the point at
      // its centre hit-tests to the badge itself.
      const onTop = await badge.evaluate((node) => {
        const box = node.getBoundingClientRect()
        const hit = document.elementFromPoint(box.left + box.width / 2, box.top + box.height / 2)
        return hit === node || node.contains(hit)
      })
      expect(onTop, `badge on top with the rail ${state}`).toBe(true)
      const rail = await page.locator('.app__sidebar').boundingBox()
      const box = await badge.boundingBox()
      expect(box!.x + box!.width, `badge inside the rail when ${state}`).toBeLessThanOrEqual(rail!.x + rail!.width)
      expect(box!.y, `badge inside the rail when ${state}`).toBeGreaterThanOrEqual(rail!.y)
    }
  })

  test('the header holds no Inbox, and the rail entry opens it', async ({ page }) => {
    await page.goto('/browse')
    await expect(page.locator('header').getByRole('button', { name: /Inbox/ })).toHaveCount(0)

    await page
      .locator('.app__nav')
      .getByRole('menuitem', { name: /^Inbox/ })
      .click()

    await expect(page).toHaveURL(/\/inbox$/)
  })
})
