// railTabs.spec.ts -- hiding a tab from one's own rail (BLOCKING.md item
// 3, step 1.4d): for this person, in this browser, across a reload; the
// palette still reaches the page.
//
// SETUP: as the other specs.

import { expect, test } from '@playwright/test'

test('a tab hidden from your rail stays hidden across a reload, and the palette still reaches it', async ({ page }) => {
  await page.goto('/')
  await page.getByLabel('Username').fill('plainuser')
  await page.getByLabel('Password').fill('plainpass123')
  await page.getByRole('button', { name: 'Log in' }).click()
  const rail = page.locator('.app__nav')
  await expect(rail.getByRole('menuitem', { name: 'Schema' })).toBeVisible()

  await page
    .locator('header')
    .getByRole('button', { name: /plainuser/i })
    .click()
  await page.getByRole('menuitem', { name: 'Your rail tabs…' }).click()
  await page.getByRole('dialog').getByText('Schema', { exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(rail.getByRole('menuitem', { name: 'Schema' })).toHaveCount(0)

  await page.reload()
  await expect(rail.getByRole('menuitem', { name: 'Query' })).toBeVisible()
  await expect(rail.getByRole('menuitem', { name: 'Schema' })).toHaveCount(0)

  await page.keyboard.press('Control+k')
  await page
    .getByRole('dialog', { name: 'Commands' })
    .getByRole('option', { name: /Schema/ })
    .first()
    .click()
  await expect(page).toHaveURL(/\/schema$/)
})
