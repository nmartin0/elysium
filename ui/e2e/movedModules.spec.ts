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
 *  styles drawing it.
 *
 *  `first`: the Inbox's first tab, open as soon as the Inbox is, so
 *  "until the tab is opened" is until the Inbox is.
 *  `probe`: what the stylesheet styles is drawn only when there is work
 *  waiting, which a fresh deployment may not have; an element of that
 *  class is put in the tab, and the stylesheet must draw it. */
const INBOX_TABS: {
  id: string
  tab: RegExp
  shows: RegExp
  styled: string
  subTab?: RegExp
  first?: boolean
  probe?: boolean
}[] = [
  // ONE BUNDLE FOR FOUR TABS: Approvals, Enrichment, Predictions, Unusual.
  {
    id: 'approvals',
    tab: /Approvals/,
    shows: /Nothing waiting|Proposed by/,
    styled: '.approvals__item',
    first: true,
    probe: true,
  },
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
    if (moved.first) expect(asked.filter((path) => path.includes(`/${moved.id}/`))).toEqual([])
    await page.locator('.app__nav').getByRole('menuitem', { name: /Inbox/ }).click()
    await expect(page.getByRole('tab', { name: moved.tab })).toBeVisible()
    if (!moved.first) expect(asked.filter((path) => path.includes(`/${moved.id}/`))).toEqual([])

    await page.getByRole('tab', { name: moved.tab }).click()
    if (moved.subTab) await page.getByRole('tab', { name: moved.subTab }).click()

    await expect(page.getByText(moved.shows).first()).toBeVisible()
    expect(asked).toContain(`/api/modules/${moved.id}/files/dist/index.js`)
    expect(asked).toContain(`/api/modules/${moved.id}/files/dist/index.css`)
    // ITS OWN STYLES ARRIVED WITH IT: an element its stylesheet styles is
    // drawn differently from the same element unstyled.
    if (moved.probe) {
      await page
        .locator('[role="tabpanel"]')
        .first()
        .evaluate((panel, name) => {
          const probe = document.createElement('div')
          probe.className = name
          probe.textContent = 'probe'
          panel.appendChild(probe)
        }, moved.styled.slice(1))
    }
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
