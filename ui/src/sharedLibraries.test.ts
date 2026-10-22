/**
 * A SHIM CANNOT FALL BEHIND THE LIBRARY IT STANDS FOR.
 *
 * Each shim lists its library's export names, read at build time
 * (@shell/build/sharedLibraries). If a library gains an export the shim
 * does not list, a module importing it fails to load in the browser
 * ("does not provide an export named ...") -- and nothing in jsdom, which
 * never uses the import map, would notice. So every shared specifier's
 * names are compared here with what the library really exports.
 */
import { resolve } from 'node:path'
import { expandSpecifiers, sharedNames } from '@shell/build/sharedLibraries'
import { describe, expect, it, vi } from 'vitest'
import { SHARED_LIBRARIES, SHARED_PACKAGES } from './sharedLibraries'

const ROOT = resolve(import.meta.dirname, '..')
const specifiers = expandSpecifiers(ROOT, { libraries: SHARED_LIBRARIES, packages: SHARED_PACKAGES })
describe('the shared libraries', () => {
  it('cover the kit, the shell and the libraries the page promises', () => {
    expect(specifiers).toContain('react')
    expect(specifiers).toContain('@elysium/shell-api/api')
    expect(specifiers).toContain('@shell/core/contract')
    expect(specifiers.some((s) => s.endsWith('.css'))).toBe(false)
  })

  it('list exactly the names each library exports', async () => {
    const listed = await sharedNames(ROOT, specifiers)

    for (const specifier of specifiers) {
      const actual = Object.keys(await vi.importActual<object>(specifier)).sort()
      expect({ specifier, names: listed.get(specifier) }).toEqual({ specifier, names: actual })
    }
  }, 60_000)
})
