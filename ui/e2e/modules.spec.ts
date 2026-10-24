// modules.spec.ts -- a sub-app loaded as a MODULE, from its own bundle,
// served by Elysium (BLOCKING.md item 3, step 1.2).
//
// The Schema graph is no longer part of the page's code. Opening /schema
// fetches its bundle from /api/modules/schema/files/, adds its stylesheet,
// and mounts the page its `activate` returns. Only a browser against the
// real server shows all of that working together: jsdom cannot import a
// bundle, and the unit tests stand in for each piece separately.
//
// SETUP: as the other specs (layout.spec.ts) -- the built bundle, the e2e
// users, uvicorn running.
//   cd ~/elysium/ui && npm run build    (builds the Schema bundle too)
//   cd ~/elysium/ui && npm run e2e

import { expect, test, type Page } from '@playwright/test'

async function logIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('plainuser')
  await page.getByLabel('Password').fill('plainpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.locator('.app__nav').getByRole('menuitem', { name: 'Query' })).toBeVisible()
}

test('the Schema graph loads from its own bundle, with its own stylesheet', async ({ page }) => {
  const fetched: string[] = []
  page.on('request', (request) => fetched.push(new URL(request.url()).pathname))
  await logIn(page)
  expect(fetched.some((path) => path.startsWith('/api/modules/schema/'))).toBe(false)

  await page.locator('.app__nav').getByRole('menuitem', { name: 'Schema' }).click()

  // The fixtures' types, drawn by the module's page.
  await expect(page.getByText('Customer').first()).toBeVisible()
  await expect(page.getByRole('alert').filter({ hasText: 'could not be loaded' })).toHaveCount(0)
  expect(fetched).toContain('/api/modules/schema/files/dist/index.js')
  // Its stylesheet, added by the shell and actually applied: the browser
  // parsed it, so its rules are in a sheet.
  const sheet = page.locator('link[data-shell-module="schema"]')
  await expect(sheet).toHaveCount(1)
  expect(await sheet.evaluate((link: HTMLLinkElement) => link.sheet !== null)).toBe(true)
})

test("a module's page opened directly, as a bookmark, loads too", async ({ page }) => {
  await logIn(page)

  await page.goto('/schema')

  await expect(page.getByText('Customer').first()).toBeVisible()
  await expect(page).toHaveURL(/\/schema$/)
})

test('Query, where a person lands, comes from its own bundle and its own stylesheet draws it', async ({ page }) => {
  // Moved in step 3. /query is the home page, so its bundle is asked for
  // as the person lands -- and must be, or they land on nothing.
  const fetched: string[] = []
  page.on('request', (request) => fetched.push(new URL(request.url()).pathname))
  await logIn(page)

  const box = page.locator('.query-panel__input')
  await expect(box).toBeVisible()
  expect(fetched).toContain('/api/modules/query/files/dist/index.js')
  expect(fetched).toContain('/api/modules/query/files/dist/index.css')
  // ITS OWN RULE DREW IT: the textarea's padding and border are its
  // stylesheet's, not those of a textarea nothing styles. (Border style
  // alone could not tell: a browser's own textarea border is solid too,
  // and a check on it passed with the stylesheet removed.)
  const [styled, bare] = await box.evaluate((el) => {
    const drawn = (of: Element) => `${getComputedStyle(of).paddingTop} ${getComputedStyle(of).borderTopLeftRadius}`
    const plain = document.createElement('textarea')
    document.body.appendChild(plain)
    const unstyled = drawn(plain)
    plain.remove()
    return [drawn(el), unstyled]
  })
  expect(styled).not.toBe(bare)
})

test('Admin comes from its own bundle when first opened, and its own stylesheet draws the user table', async ({
  page,
}) => {
  // Moved in step 3, after the server's views were split out of it to
  // System -> Server.
  const fetched: string[] = []
  page.on('request', (request) => fetched.push(new URL(request.url()).pathname))
  await page.goto('/')
  await page.getByLabel('Username').fill('adminuser')
  await page.getByLabel('Password').fill('adminpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  const rail = page.locator('.app__nav')
  await expect(rail.getByRole('menuitem', { name: 'Admin' })).toBeVisible()
  expect(fetched.some((path) => path.startsWith('/api/modules/admin/'))).toBe(false)

  await rail.getByRole('menuitem', { name: 'Admin' }).click()
  const table = page.locator('.user-table').first()
  await expect(table).toBeVisible()
  expect(fetched).toContain('/api/modules/admin/files/dist/index.js')
  // ITS OWN RULE: a table nothing styles has separate borders.
  expect(await table.evaluate((el) => getComputedStyle(el).borderCollapse)).toBe('collapse')
})
