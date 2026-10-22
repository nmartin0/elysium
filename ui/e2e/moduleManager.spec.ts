// moduleManager.spec.ts -- the module manager changing the deployment
// (BLOCKING.md item 3, step 1.4c): a module turned off leaves the rail,
// here at once and in another open tab on its next request.
//
// IT WRITES modules.yaml INTO THE SERVER'S CONFIGURATION DIRECTORY -- in
// development that is tests/integration/fixtures, which nothing should
// write. So it runs only when told the server is using a COPY:
//
//   cp -r tests/integration/fixtures /tmp/e2e-config
//   ELYSIUM_CONFIG_DIR=/tmp/e2e-config uvicorn api.app:app
//   E2E_MAY_WRITE_CONFIG=1 npm run e2e
//
// SETUP otherwise as the other specs (opsuser, from create_e2e_users).

import { expect, test, type Page } from '@playwright/test'

test.skip(
  !process.env.E2E_MAY_WRITE_CONFIG,
  'writes modules.yaml: run against a server on a copy of the configuration, with E2E_MAY_WRITE_CONFIG=1',
)

async function logIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('opsuser')
  await page.getByLabel('Password').fill('opspass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.locator('.app__nav')).toBeVisible()
}

const rail = (page: Page) => page.locator('.app__nav')

test('a module turned off leaves the rail here at once, and in another open tab on its next request', async ({
  page,
  context,
}) => {
  await logIn(page)
  const other = await context.newPage()
  await other.goto('/query')
  await expect(rail(other).getByRole('menuitem', { name: 'Schema' })).toBeVisible()

  const before = await rail(page).getByRole('menuitem').allTextContents()
  await page.goto('/system/modules')
  const schema = page.getByRole('checkbox', { name: 'Schema' })
  await expect(schema).toBeChecked()
  await schema.click({ force: true })
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
  await expect(rail(page).getByRole('menuitem', { name: 'Schema' })).toHaveCount(0)

  // The other tab learns of it on its next request, which carries the
  // new generation -- here, opening Browse.
  await rail(other).getByRole('menuitem', { name: 'Browse' }).click()
  await expect(rail(other).getByRole('menuitem', { name: 'Schema' })).toHaveCount(0)

  // And back on -- IN ITS PLACE, leaving the deployment as it was found.
  await page.getByRole('checkbox', { name: 'Schema' }).click({ force: true })
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(rail(page).getByRole('menuitem', { name: 'Schema' })).toBeVisible()
  expect(await rail(page).getByRole('menuitem').allTextContents()).toEqual(before)
})

test('home must open something: an arrangement that would not load is refused, and nothing changes', async ({
  page,
}) => {
  await logIn(page)
  await page.goto('/system/modules')
  // Query is home; turning it off leaves home opening nothing.
  await page.getByRole('checkbox', { name: 'Query' }).click({ force: true })
  await page.getByRole('button', { name: 'Save' }).click()

  await expect(page.getByRole('alert').filter({ hasText: 'Not saved' })).toContainText('would not load')
  await expect(rail(page).getByRole('menuitem', { name: 'Query' })).toBeVisible()
})

test('turning a queue module off takes its Inbox tab away, and the Inbox stands (slots, step 1.5b)', async ({
  page,
}) => {
  await logIn(page)
  await page.goto('/inbox')
  await expect(page.getByRole('tab', { name: /Identity/ })).toBeVisible()

  await page.goto('/system/modules')
  await page.getByRole('checkbox', { name: 'Identity' }).click({ force: true })
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()

  await page.goto('/inbox')
  await expect(page.getByRole('tab', { name: /Approvals/ })).toBeVisible()
  await expect(page.getByRole('tab', { name: /Identity/ })).toHaveCount(0)

  // Back on, as it was found.
  await page.goto('/system/modules')
  await page.getByRole('checkbox', { name: 'Identity' }).click({ force: true })
  await page.getByRole('button', { name: 'Save' }).click()
  await expect(page.getByRole('status').filter({ hasText: 'Saved.' })).toBeVisible()
})
