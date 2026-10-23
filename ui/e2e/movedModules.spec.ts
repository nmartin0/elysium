// movedModules.spec.ts -- sub-apps moved out of Elysium's page into
// bundles of their own (BLOCKING.md item 3, step 3), one by one: each
// one's code arrives from its bundle, and only when it is first shown.
// A module moved later adds its case here.
//
// SETUP: as the other specs.

import { expect, test, type Page } from '@playwright/test'

async function logIn(page: Page) {
  await page.goto('/')
  await page.getByLabel('Username').fill('adminuser')
  await page.getByLabel('Password').fill('adminpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page.locator('.app__nav')).toBeVisible()
}

/** The module files the page has asked Elysium for, so far. */
function bundlesAskedFor(page: Page): string[] {
  const asked: string[] = []
  page.on('request', (request) => {
    const path = new URL(request.url()).pathname
    if (path.startsWith('/api/modules/')) asked.push(path)
  })
  return asked
}

test("the Identity tab's code comes from its own bundle, when the tab is first opened", async ({ page }) => {
  const asked = bundlesAskedFor(page)
  await logIn(page)
  await page.locator('.app__nav').getByRole('menuitem', { name: /Inbox/ }).click()
  await expect(page.getByRole('tab', { name: /Identity/ })).toBeVisible()
  expect(asked.filter((path) => path.includes('/identity/'))).toEqual([])

  await page.getByRole('tab', { name: /Identity/ }).click()

  await expect(page.getByText(/Pairs the matcher believes may be the same thing/)).toBeVisible()
  expect(asked).toContain('/api/modules/identity/files/dist/index.js')
  expect(asked).toContain('/api/modules/identity/files/dist/index.css')
  // ITS OWN STYLES ARRIVED WITH IT: the lede is drawn in the secondary
  // colour its stylesheet gives it, not the page's body colour.
  const lede = page.locator('.identity__lede')
  const body = page.locator('body')
  expect(await lede.evaluate((el) => getComputedStyle(el).color)).not.toBe(
    await body.evaluate((el) => getComputedStyle(el).color),
  )
})
