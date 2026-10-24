// safeMode.spec.ts -- safe mode (BLOCKING.md item 3, step 1.4b): the page
// loaded with only the pinned modules, in this tab, until left.
//
// Only a browser shows it: entering and leaving RELOAD the page (a
// module's imported code stays until a reload), and what carries safe
// mode across reloads is the tab's own session storage.
//
// SETUP: as the other specs, with the e2e users created afresh (opsuser).

import { expect, test, type Page } from '@playwright/test'

async function logIn(page: Page, username: string, password: string) {
  await page.goto('/')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.locator('.app__nav')).toBeVisible()
}

const banner = (page: Page) => page.locator('.shell__safe-mode')
const railNames = (page: Page) => page.locator('.app__nav').getByRole('menuitem').allTextContents()

test('/?safe loads only the pinned modules, keeps doing so across a reload, and leaves cleanly', async ({ page }) => {
  await logIn(page, 'opsuser', 'opspass123')
  // WAITED FOR, not read at once: the rail is drawn when the feed arrives,
  // a moment after the frame -- read at once, it was sometimes empty
  // (seen once in a full run, 22 October).
  await expect(page.locator('.app__nav').getByRole('menuitem', { name: 'Schema' })).toBeVisible()

  await page.goto('/?safe')

  await expect(banner(page)).toContainText('Safe mode.')
  // Home moved to the one pinned module's page, and the marker left the
  // address, so a link copied now does not carry it.
  await expect(page).toHaveURL(/\/system\/modules$/)
  // THE SERVER'S CONTROLS TOO (step 3): pinned, so in safe mode -- when
  // someone most needs to see the configuration and reload it.
  expect(await railNames(page)).toEqual(['Modules', 'Add-on servers', 'Server'])
  const schema = page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: /Schema/ }) })
  await expect(schema.getByRole('cell').nth(2)).toHaveText('Off in safe mode')

  await page.reload()
  await expect(banner(page)).toBeVisible()

  await banner(page).getByRole('button', { name: 'Leave safe mode' }).click()
  await expect(banner(page)).toHaveCount(0)
  await expect(page.locator('.app__nav').getByRole('menuitem', { name: 'Schema' })).toBeVisible()
})

test('the user menu reloads into it, and someone offered no system sub-app still gets the way out', async ({
  page,
}) => {
  await logIn(page, 'plainuser', 'plainpass123')

  await page
    .locator('header')
    .getByRole('button', { name: /plainuser/i })
    .click()
  await page.getByRole('menuitem', { name: 'Reload in safe mode' }).click()

  await expect(banner(page)).toBeVisible()
  // The feed has arrived -- an empty rail is also what shows before it
  // does -- and offered nothing to open.
  await expect(page.locator('main')).toContainText('Nothing loaded opens this page')
  expect(await railNames(page)).toEqual([])
  await banner(page).getByRole('button', { name: 'Leave safe mode' }).click()
  await expect(page.locator('.app__nav').getByRole('menuitem', { name: 'Query' })).toBeVisible()
})

test('it is this tab only: another tab opened meanwhile loads everything', async ({ page, context }) => {
  await logIn(page, 'opsuser', 'opspass123')
  await page.goto('/?safe')
  await expect(banner(page)).toBeVisible()

  const other = await context.newPage()
  await other.goto('/')
  await expect(other.locator('.app__nav').getByRole('menuitem', { name: 'Schema' })).toBeVisible()
  await expect(other.locator('.shell__safe-mode')).toHaveCount(0)
})
