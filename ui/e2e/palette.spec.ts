// palette.spec.ts -- a module's commands in the shell's palette, supplied
// by the module's own code (BLOCKING.md item 3, step 1.3b).
//
// Only a browser against the real server shows the whole chain: the feed
// carrying Browse's `onPalette` activation event from its module.json,
// the shell importing Browse's palette code when the palette first opens
// -- on a screen Browse has never been opened on -- and Browse's commands
// listed and working. The unit tests stand in for each link separately.
//
// SETUP: as the other specs (layout.spec.ts).

import { expect, test } from '@playwright/test'

test("Browse's commands are in the palette before Browse is ever opened", async ({ page }) => {
  const fetched: string[] = []
  page.on('request', (request) => fetched.push(new URL(request.url()).pathname))
  await page.goto('/')
  await page.getByLabel('Username').fill('plainuser')
  await page.getByLabel('Password').fill('plainpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL(/\/query$/)

  // Browse's palette fetches the reader's saved views when the palette
  // opens, and not before: nothing of it runs with the page.
  const savedViews = () => fetched.filter((path) => path === '/api/saved-views').length
  expect(savedViews()).toBe(0)
  await page.keyboard.press('Control+k')
  const palette = page.getByRole('dialog', { name: 'Commands' })
  await expect(palette).toBeVisible()
  await expect.poll(savedViews).toBe(1)

  const browseCustomer = palette.getByRole('option', { name: /Browse Customer/ })
  await expect(browseCustomer).toBeVisible()
  await browseCustomer.click()

  await expect(page).toHaveURL(/\/browse\?type=Customer$/)
})

test('a search suggestion comes from Browse too', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('plainuser')
  await page.getByLabel('Password').fill('plainpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  await expect(page).toHaveURL(/\/query$/)

  await page.keyboard.press('Control+k')
  await page.getByLabel('Search commands').fill('ada')

  await expect(page.getByRole('option', { name: /Search Customer for .ada./ })).toBeVisible()
})
