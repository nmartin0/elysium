// system.spec.ts -- the system sub-app (BLOCKING.md item 3, steps 1.4 and
// 2.2): the Modules and Add-on servers pages, pinned, offered only with
// manage:deployment.
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

test('the System pages are last on the rail, and Modules lists every module with how it loads here', async ({
  page,
}) => {
  await logIn(page, 'opsuser', 'opspass123')
  const rail = page.locator('.app__nav')
  const entries = rail.getByRole('menuitem')
  await expect(entries.last()).toHaveAccessibleName('Add-on servers')
  const modules = entries.nth((await entries.count()) - 2)
  await expect(modules).toHaveAccessibleName('Modules')

  await modules.click()
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

// ADD-ON SERVERS (step 2.2): the page is there for manage:deployment, and
// says so when no module this deployment lists has a server -- the e2e
// deployment lists none. Its servers starting, failing and restarting are
// tests/integration/test_addon_lifecycle.py's, against real processes.
test('the Add-on servers page says when no module has a server', async ({ page }) => {
  await logIn(page, 'opsuser', 'opspass123')
  await page.locator('.app__nav').getByRole('menuitem', { name: 'Add-on servers' }).click()
  await expect(page).toHaveURL(/\/system\/addons$/)
  await expect(page.getByRole('heading', { name: 'Add-on servers' })).toBeVisible()
  await expect(page.getByText('No add-on servers')).toBeVisible()
})
