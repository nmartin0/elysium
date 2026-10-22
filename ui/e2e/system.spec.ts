// system.spec.ts -- the shell's system sub-app (BLOCKING.md item 3, step
// 1.4): the Modules page, pinned, offered only with manage:deployment.
//
// SETUP: as the other specs, with the e2e users created afresh -- opsuser
// was added for this file:
//   cd ~/elysium && python -m scripts.create_e2e_users --yes-this-is-development

import { expect, test, type Page } from '@playwright/test'

async function logIn(page: Page, username: string, password: string) {
  await page.goto('/')
  await page.getByLabel('Username').fill(username)
  await page.getByLabel('Password').fill(password)
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.locator('.app__nav')).toBeVisible()
}

test('the Modules page is last on the rail, and lists every module with how it loads here', async ({ page }) => {
  await logIn(page, 'opsuser', 'opspass123')
  const rail = page.locator('.app__nav')
  const entries = rail.getByRole('menuitem')
  await expect(entries.last()).toHaveAccessibleName('Modules')

  await entries.last().click()
  await expect(page).toHaveURL(/\/system\/modules$/)
  const row = (name: string) =>
    page.getByRole('row').filter({ has: page.getByRole('rowheader', { name: new RegExp(name) }) })
  await expect(row('System')).toContainText('Pinned')
  await expect(row('Schema')).toContainText('Its own bundle')
  await expect(row('Schema').getByRole('cell').nth(2)).toHaveText(/^Not loaded yet/)

  // LIVE: opening the Schema graph loads its bundle, and the page says so
  // on return without a reload.
  await rail.getByRole('menuitem', { name: 'Schema' }).click()
  await expect(page.getByText('Customer').first()).toBeVisible()
  await rail.getByRole('menuitem', { name: 'Modules' }).click()
  // The status cell exactly: "Not loaded yet" must not pass for it.
  await expect(row('Schema').getByRole('cell').nth(2)).toHaveText('Loaded')
})

test('someone without manage:deployment is not offered it', async ({ page }) => {
  await logIn(page, 'plainuser', 'plainpass123')
  await expect(page.locator('.app__nav').getByRole('menuitem', { name: 'Modules' })).toHaveCount(0)
  await page.goto('/system/modules')
  await expect(page.getByRole('table')).toHaveCount(0)
})
