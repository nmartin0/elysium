// @vitest-environment node
import { mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, describe, expect, it } from 'vitest'
import {
  REGISTRY,
  expandSpecifiers,
  exportedNames,
  importMap,
  registrySource,
  sharedNames,
  shimFileName,
  shimSource,
} from './sharedLibraries'

/** Evaluate generated source as a real ES module, the way a browser would. */
function evaluate(source: string): Promise<Record<string, unknown>> {
  return import(/* @vite-ignore */ `data:text/javascript,${encodeURIComponent(source)}`)
}

const g = globalThis as Record<string, unknown>
afterEach(() => {
  delete g[REGISTRY]
})

describe('shimFileName', () => {
  it('never gives two specifiers one file', () => {
    expect(shimFileName('@a/b')).not.toBe(shimFileName('_a/b'))
    expect(shimFileName('react-dom/client')).toBe('react-dom_2fclient.js')
  })
})

describe('shimSource', () => {
  it("hands out the page's registered copy, named exports and default", async () => {
    const copy = { default: 'the default', useState: 'the hook' }
    g[REGISTRY] = { has: (s: string) => s === 'lib', load: async () => copy }

    const shim = await evaluate(shimSource('lib', ['default', 'useState']))

    expect(shim.useState).toBe('the hook')
    expect(shim.default).toBe('the default')
  })

  it('refuses, by name, a library the page does not share', async () => {
    g[REGISTRY] = { has: () => false, load: async () => ({}) }

    await expect(evaluate(shimSource('missing-lib', ['x']))).rejects.toThrow(/does not share missing-lib/)
  })

  it('refuses an export name it cannot write as a binding', () => {
    expect(() => shimSource('lib', ['ok', 'not-ok'])).toThrow(/not-ok/)
  })
})

describe('registrySource', () => {
  it('gives every shim of one library the same namespace', async () => {
    await evaluate(registrySource(['node:path']))
    const registry = g[REGISTRY] as {
      has(s: string): boolean
      load(s: string): Promise<unknown>
      specifiers(): string[]
    }

    expect(registry.has('node:path')).toBe(true)
    expect(registry.has('node:fs')).toBe(false)
    expect(registry.specifiers()).toEqual(['node:path'])
    expect(await registry.load('node:path')).toBe(await registry.load('node:path'))
  })
})

describe('importMap', () => {
  it('sends each specifier to its shim under the base', () => {
    expect(importMap(['react'], '/app/').imports).toEqual({ react: '/app/shared/react.js' })
  })
})

describe('exportedNames', () => {
  it('lists value exports and the default, never types', () => {
    const source = `
      export type T = string
      export interface I { a: number }
      export const a = 1
      export function b() {}
      const c = 2
      export { c as renamed }
      export default function Page() {}
    `
    expect(exportedNames('x.tsx', source)).toEqual(['a', 'b', 'default', 'renamed'])
  })

  it('refuses `export *`, whose names a parse cannot see', () => {
    expect(() => exportedNames('x.ts', "export * from './y'")).toThrow(/export \*/)
  })
})

describe('expandSpecifiers and sharedNames', () => {
  function project() {
    const root = mkdtempSync(join(tmpdir(), 'shared-'))
    writeFileSync(join(root, 'package.json'), '{"name":"host","type":"module"}')
    // OUR OWN package: TypeScript, read by parsing.
    const ours = join(root, 'packages', 'kit')
    mkdirSync(join(ours, 'src'), { recursive: true })
    writeFileSync(
      join(ours, 'package.json'),
      JSON.stringify({
        name: '@x/kit',
        type: 'module',
        exports: { './api': './src/api.ts', './theme.css': './src/theme.css' },
      }),
    )
    writeFileSync(join(ours, 'src', 'api.ts'), 'export const call = () => 1\nexport type Shape = {}\n')
    // Linked into node_modules, as npm links a `file:` dependency.
    mkdirSync(join(root, 'node_modules', '@x'), { recursive: true })
    symlinkSync(ours, join(root, 'node_modules', '@x', 'kit'))
    // AN NPM PACKAGE, CommonJS: read by importing it in Node.
    const lib = join(root, 'node_modules', 'cjs-lib')
    mkdirSync(lib)
    writeFileSync(join(lib, 'package.json'), '{"name":"cjs-lib","main":"index.js"}')
    writeFileSync(join(lib, 'index.js'), 'exports.alpha = 1; exports.beta = 2;')
    return root
  }

  it("shares every one of a package's exports except stylesheets", () => {
    expect(expandSpecifiers(project(), { libraries: ['cjs-lib'], packages: ['@x/kit'] })).toEqual([
      'cjs-lib',
      '@x/kit/api',
    ])
  })

  it('reads names exactly, from CommonJS by importing and from TypeScript by parsing', async () => {
    const root = project()

    const names = await sharedNames(root, ['cjs-lib', '@x/kit/api'])

    expect(names.get('cjs-lib')).toEqual(['alpha', 'beta', 'default'])
    expect(names.get('@x/kit/api')).toEqual(['call'])
  })
})
