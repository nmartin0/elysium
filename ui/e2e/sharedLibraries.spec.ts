// sharedLibraries.spec.ts -- a module built apart from the page gets the
// PAGE'S OWN copies of the shared libraries (BLOCKING.md item 3, step 1.2).
//
// Only a browser can show this: jsdom never reads the import map. The
// module here is written by hand, with nothing but bare imports, exactly
// as a separately built bundle leaves them, and served by intercepting
// its address, so no test fixture ships in the build.
//
// THE CONTROL WAS RUN WHEN THIS WAS WRITTEN (21 October): the same
// component built with React bundled privately rendered nothing and threw
// "Cannot read properties of null (reading 'useState')" -- two Reacts
// cannot share one tree. Here, the hooks work, so the React is one.
//
// Needs no sign-in: the import map and the registry are on every page,
// the login page included. Runs against the built bundle like the rest:
//   cd ~/elysium/ui && npm run build && npm run e2e

import { expect, test } from '@playwright/test'

const MODULE = `
import { useState, createElement } from 'react'
import { jsx } from 'react/jsx-runtime'
import { useInRouterContext } from 'react-router-dom'
import { Button } from '@blueprintjs/core'
import ErrorState from '@elysium/shell-api/components/ErrorState'
import { getErrorMessage } from '@elysium/shell-api/api'

export { useState, useInRouterContext }
export function Counter() {
  const [n, setN] = useState(0)
  return createElement('div', null,
    jsx(Button, { onClick: () => setN(n + 1), children: 'clicked ' + n }),
    jsx(ErrorState, { children: getErrorMessage(new Error('from the kit')) }))
}
`

const UNSHARED = `import { Add } from '@blueprintjs/icons'\nexport { Add }\n`

test.beforeEach(async ({ page }) => {
  await page.route('**/__e2e__/module.js', (route) => route.fulfill({ contentType: 'text/javascript', body: MODULE }))
  await page.route('**/__e2e__/unshared.js', (route) =>
    route.fulfill({ contentType: 'text/javascript', body: UNSHARED }),
  )
  await page.goto('/')
})

test("a separately built module renders with the page's React, Blueprint and kit", async ({ page }) => {
  const result = await page.evaluate(async () => {
    const shared = (globalThis as unknown as { __shellShared: { load(s: string): Promise<Record<string, unknown>> } })
      .__shellShared
    const address: string = '/__e2e__/module.js'
    const mod = (await import(/* @vite-ignore */ address)) as Record<string, unknown>
    const react = await shared.load('react')
    const router = await shared.load('react-router-dom')
    const { createRoot } = (await shared.load('react-dom/client')) as {
      createRoot(el: Element): { render(node: unknown): void }
    }
    const { jsx } = (await shared.load('react/jsx-runtime')) as { jsx(type: unknown, props: object): unknown }
    const host = document.createElement('div')
    host.id = 'module-host'
    document.body.appendChild(host)
    createRoot(host).render(jsx(mod.Counter, {}))
    return {
      sameUseState: mod.useState === react.useState,
      sameRouter: mod.useInRouterContext === router.useInRouterContext,
    }
  })

  expect(result.sameUseState).toBe(true)
  expect(result.sameRouter).toBe(true)
  const host = page.locator('#module-host')
  await host.getByRole('button').click()
  await host.getByRole('button').click()
  await expect(host.getByRole('button')).toHaveText('clicked 2')
  await expect(host.getByRole('button')).toHaveClass(/bp6-button/)
  await expect(host.getByRole('alert')).toHaveText(/from the kit/)
})

test('a library the page does not share cannot be imported by a module', async ({ page }) => {
  const outcome = await page.evaluate(async () => {
    try {
      const address: string = '/__e2e__/unshared.js'
      await import(/* @vite-ignore */ address)
      return 'loaded'
    } catch (error) {
      return String(error)
    }
  })

  // Not in the import map, so the bare specifier cannot even resolve: a
  // module must bundle what the page does not promise.
  expect(outcome).toMatch(/@blueprintjs\/icons/)
})
