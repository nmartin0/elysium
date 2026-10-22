// @vitest-environment node
/**
 * `npm run dev` CAN LOAD THE GENERIC SHELL.
 *
 * It could not, for the whole of the commit that added @shell/core: the
 * dev server answered 403 for every file in ../shell, which Vite does not
 * serve unless told to, and the app never loaded. A production build
 * reads the files directly and jsdom never asks the dev server, so no
 * test could see it. This one asks the real dev server, built from the
 * real config.
 */
import { resolve } from 'node:path'
import { createServer, type ViteDevServer } from 'vite'
import { afterAll, beforeAll, describe, expect, it } from 'vitest'

const ROOT = resolve(import.meta.dirname, '..')
let server: ViteDevServer
let base = ''

beforeAll(async () => {
  server = await createServer({
    root: ROOT,
    configFile: resolve(ROOT, 'vite.config.ts'),
    logLevel: 'silent',
    server: { port: 0, strictPort: false, hmr: false },
  })
  await server.listen()
  const address = server.httpServer?.address()
  if (address === null || address === undefined || typeof address === 'string') throw new Error('no port')
  base = `http://localhost:${address.port}`
}, 60_000)

afterAll(async () => {
  await server?.close()
})

describe('the dev server', () => {
  it('serves the generic shell, which lives outside this project', async () => {
    const response = await fetch(`${base}/@fs${resolve(ROOT, '..', 'shell', 'core', 'src', 'contract.ts')}`)

    expect(response.status).toBe(200)
  })

  it('still refuses a file outside both', async () => {
    const response = await fetch(`${base}/@fs/etc/hostname`)

    expect(response.status).toBe(403)
  })

  it('serves the shared-library shims and the import map', async () => {
    const page = await (await fetch(`${base}/`)).text()
    const shim = await fetch(`${base}/shared/react.js`)

    expect(page).toContain('<script type="importmap">')
    expect(shim.status).toBe(200)
    expect(await shim.text()).toContain('export const {')
  })
})
