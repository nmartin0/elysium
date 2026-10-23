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

/** An Inbox tab moved into a bundle of its own: nothing of it fetched
 *  until the tab is opened, then its code and stylesheet, and its own
 *  styles drawing it. */
const INBOX_TABS: { id: string; tab: RegExp; shows: RegExp; styled: string; subTab?: RegExp }[] = [
  {
    id: 'identity',
    tab: /Identity/,
    shows: /Pairs the matcher believes may be the same thing/,
    styled: '.identity__lede',
  },
  // Its own sub-tab first: the reminders form is what its stylesheet lays out.
  { id: 'notifications', tab: /Notifications/, shows: /Times are in/, styled: '.reminders', subTab: /Reminders/ },
]

for (const moved of INBOX_TABS) {
  test(`the ${moved.id} tab's code comes from its own bundle, when the tab is first opened`, async ({ page }) => {
    const asked = bundlesAskedFor(page)
    await logIn(page)
    await page.locator('.app__nav').getByRole('menuitem', { name: /Inbox/ }).click()
    await expect(page.getByRole('tab', { name: moved.tab })).toBeVisible()
    expect(asked.filter((path) => path.includes(`/${moved.id}/`))).toEqual([])

    await page.getByRole('tab', { name: moved.tab }).click()
    if (moved.subTab) await page.getByRole('tab', { name: moved.subTab }).click()

    await expect(page.getByText(moved.shows).first()).toBeVisible()
    expect(asked).toContain(`/api/modules/${moved.id}/files/dist/index.js`)
    expect(asked).toContain(`/api/modules/${moved.id}/files/dist/index.css`)
    // ITS OWN STYLES ARRIVED WITH IT: an element its stylesheet styles is
    // drawn differently from the same element unstyled.
    const styled = page.locator(moved.styled).first()
    await expect(styled).toBeVisible()
    expect(await styled.evaluate((el) => getComputedStyle(el).display + getComputedStyle(el).color)).not.toBe(
      await styled.evaluate((el) => {
        const bare = document.createElement(el.tagName)
        document.body.appendChild(bare)
        const style = getComputedStyle(bare).display + getComputedStyle(bare).color
        bare.remove()
        return style
      }),
    )
  })
}
