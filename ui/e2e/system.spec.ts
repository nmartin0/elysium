// system.spec.ts -- the system sub-app (BLOCKING.md item 3, steps 1.4,
// 2.2 and 3): the Modules, Add-on servers and Server pages, pinned,
// offered only with manage:deployment.
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
  await expect(entries.last()).toHaveAccessibleName('Server')
  await expect(entries.nth((await entries.count()) - 2)).toHaveAccessibleName('Add-on servers')
  const modules = entries.nth((await entries.count()) - 3)
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

// THE SERVER (step 3): Elysium's own controls, split out of Admin, for
// whoever runs the server. Each view's own behaviour is its unit tests';
// this is that the page is there, loads them, and keeps the view in the
// address.
test("the server's controls are under System, Server, and a view is an address", async ({ page }) => {
  await logIn(page, 'opsuser', 'opspass123')
  await page.locator('.app__nav').getByRole('menuitem', { name: 'Server', exact: true }).click()
  await expect(page).toHaveURL(/\/system\/server$/)
  await expect(page.getByRole('heading', { name: 'Configuration history' })).toBeVisible()

  await page.getByRole('button', { name: /Mirror/ }).click()
  await expect(page).toHaveURL(/view=mirror/)
  await page.reload()
  await expect(page.getByRole('button', { name: /Sync now/ })).toBeVisible()
})

test('Admin keeps people and roles, and an account administrator is not offered the server', async ({ page }) => {
  await logIn(page, 'adminuser', 'adminpass123')
  const rail = page.locator('.app__nav')
  await expect(rail.getByRole('menuitem', { name: 'Server', exact: true })).toHaveCount(0)

  await rail.getByRole('menuitem', { name: 'Admin' }).click()
  await expect(page.getByRole('button', { name: /^Users$/ })).toBeVisible()
  await expect(page.getByRole('button', { name: /^Roles$/ })).toBeVisible()
  for (const moved of ['Deployment', 'Silos', 'Metrics', 'Mirror', 'Cleaning']) {
    await expect(page.getByRole('button', { name: new RegExp(`^${moved}$`) })).toHaveCount(0)
  }
})
