/**
 * Shared libraries: ONE COPY of React, the router, the kit and the rest,
 * used by the page and by every module built apart from it.
 *
 * BLOCKING.md item 3: "SHARED LIBRARIES ARE FIXED AT PAGE LOAD ... by
 * import map". A module is built with these left as bare imports
 * (`import { useState } from 'react'`). The page's import map sends each
 * one to a small SHIM here, and the shim hands out the copy the page
 * itself is running -- registered on `globalThis.__shellShared` by
 * `virtual:shared-registry`, which the page imports first.
 *
 * WHY THE PAGE'S OWN COPY, rather than building the libraries as files
 * of their own (Native Federation's way: "places ... the libraries to be
 * shared in their own bundles"). Some shared code keeps state at module
 * level -- Elysium's API client holds the session-expiry handler and the
 * last configuration generation it saw -- so there must be exactly one
 * instance, and the page's is the one already running. The page's own
 * build stays as it is; nothing about how it bundles React changes, in
 * development or in production, which is what lets a module load the
 * same way in both (decided 21 October: one path).
 *
 * THE SHIM NEEDS THE NAMES, because an ES module's exports are fixed when
 * it is parsed. They are read two ways, both exact:
 * - an npm package is IMPORTED IN NODE and its keys listed. Vite's own
 *   server-side loader cannot do this here -- it evaluates React's
 *   CommonJS as ESM and fails with "module is not defined" -- but Node's
 *   loader reads CommonJS named exports itself.
 * - a package of our own (TypeScript, importing CSS, unrunnable in Node)
 *   is PARSED, and its export statements read. Exact because none of
 *   them uses `export *`, which a parse cannot see through; `sharedNames`
 *   refuses one rather than guessing.
 * A test in each host compares these names with the live registry, so a
 * shim cannot fall behind the code it stands for.
 *
 * SHARED LAZILY. A shared library must be available WHOLE -- a module
 * may use any part of it -- but the page should not download what no
 * module has asked for. Measured on Elysium's page: registering every
 * library eagerly took the first load from 1.97 MB to 3.49 MB (Blueprint's
 * icons 770 KB, ECharts' charts and components 452 KB). So the registry
 * holds LOADERS, `() => import(...)`, and a shim awaits its library the
 * first time a module imports it (top-level await). The bundler still
 * emits each library once -- what the page uses itself stays where it
 * was, and the rest is split into files fetched only on demand -- so a
 * module and the page still share one instance.
 */
import { readFileSync, realpathSync } from 'node:fs'
import { createRequire } from 'node:module'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { parseSync, type Plugin } from 'vite'

/** Where the page keeps its shared copies, by specifier. */
export const REGISTRY = '__shellShared'
/** The virtual module the page imports, first, to fill the registry. */
export const REGISTRY_MODULE = 'virtual:shared-registry'
/** Where the shims are served, under the page's base. */
export const SHIM_DIRECTORY = 'shared'

export interface SharedLibrariesOptions {
  /** Bare specifiers shared exactly as written, e.g. `react-dom/client`. */
  libraries: string[]
  /** Packages whose EVERY `exports` entry is shared (stylesheets excepted). */
  packages?: string[]
}

/**
 * A file name for a specifier's shim: reversible, so two specifiers can
 * never share one -- `@a/b` and `_a/b` must not collide.
 */
export function shimFileName(specifier: string): string {
  const safe = specifier.replace(/[^a-zA-Z0-9.-]/g, (c) => `_${c.charCodeAt(0).toString(16)}`)
  return `${safe}.js`
}

const IDENTIFIER = /^[A-Za-z_$][\w$]*$/

/** The shim for one specifier: awaits the page's registered copy. */
export function shimSource(specifier: string, names: readonly string[]): string {
  const named = names.filter((name) => name !== 'default')
  const odd = named.filter((name) => !IDENTIFIER.test(name))
  if (odd.length > 0) {
    throw new Error(`${specifier}: cannot share exports that are not identifiers: ${odd.join(', ')}`)
  }
  const lines = [
    `const shared = globalThis.${REGISTRY};`,
    `if (shared === undefined || !shared.has(${JSON.stringify(specifier)})) throw new Error(${JSON.stringify(
      `This page does not share ${specifier}; a module importing it cannot load here.`,
    )});`,
    `const m = await shared.load(${JSON.stringify(specifier)});`,
  ]
  if (names.includes('default')) lines.push('export default m.default;')
  if (named.length > 0) lines.push(`export const { ${named.join(', ')} } = m;`)
  return lines.join('\n') + '\n'
}

/**
 * The source of `virtual:shared-registry`: a loader per specifier. No
 * cache of its own: an ES module is instantiated once per URL, so every
 * `import()` of one library -- from every shim -- gets the one namespace.
 */
export function registrySource(specifiers: readonly string[]): string {
  const loaders = specifiers.map((s) => `  [${JSON.stringify(s)}, () => import(${JSON.stringify(s)})],`)
  return [
    'const loaders = new Map([',
    ...loaders,
    ']);',
    `globalThis.${REGISTRY} = Object.freeze({`,
    '  has: (specifier) => loaders.has(specifier),',
    '  specifiers: () => [...loaders.keys()],',
    '  load: (specifier) => loaders.get(specifier)(),',
    '});',
    '',
  ].join('\n')
}

/** The page's import map: every shared specifier to its shim. */
export function importMap(specifiers: readonly string[], base: string): { imports: Record<string, string> } {
  const imports: Record<string, string> = {}
  for (const s of specifiers) imports[s] = `${base}${SHIM_DIRECTORY}/${shimFileName(s)}`
  return { imports }
}

/** The names a TypeScript module exports, read from its source. */
export function exportedNames(fileName: string, source: string): string[] {
  const parsed = parseSync(fileName, source)
  if (parsed.errors.length > 0) throw new Error(`${fileName}: cannot be parsed to list its exports`)
  const names = new Set<string>()
  for (const statement of parsed.module.staticExports) {
    for (const entry of statement.entries) {
      if (entry.isType) continue
      if (entry.exportName.kind === 'Default') names.add('default')
      else if (entry.exportName.kind === 'Name' && entry.exportName.name) names.add(entry.exportName.name)
      else throw new Error(`${fileName}: \`export *\` hides its names from the shims; export them by name`)
    }
  }
  return [...names].sort()
}

/** Every shared specifier: the libraries, and each package's exports. */
export function expandSpecifiers(root: string, options: SharedLibrariesOptions): string[] {
  const specifiers = [...options.libraries]
  for (const pkg of options.packages ?? []) {
    const manifest = JSON.parse(readFileSync(join(root, 'node_modules', pkg, 'package.json'), 'utf8')) as {
      exports?: Record<string, string>
    }
    for (const [subpath, target] of Object.entries(manifest.exports ?? {})) {
      if (target.endsWith('.css')) continue
      specifiers.push(subpath === '.' ? pkg : `${pkg}/${subpath.replace(/^\.\//, '')}`)
    }
  }
  return specifiers
}

/** The names each specifier exports, read as the module docstring says. */
export async function sharedNames(root: string, specifiers: readonly string[]): Promise<Map<string, string[]>> {
  const requireFromRoot = createRequire(join(root, 'package.json'))
  const result = new Map<string, string[]>()
  for (const specifier of specifiers) {
    const resolved = realpathSync(requireFromRoot.resolve(specifier))
    const ours = /\.(m?ts|tsx)$/.test(resolved) && !resolved.includes(`${'/'}node_modules${'/'}`)
    if (ours) {
      result.set(specifier, exportedNames(resolved, readFileSync(resolved, 'utf8')))
    } else {
      const namespace = (await import(pathToFileURL(resolved).href)) as Record<string, unknown>
      result.set(specifier, Object.keys(namespace).sort())
    }
  }
  return result
}

/** The Vite plugin: the registry, the shims and the import map. */
export function sharedLibraries(options: SharedLibrariesOptions): Plugin {
  let root = process.cwd()
  let base = '/'
  let specifiers: string[] = []
  let shims = new Map<string, string>()

  async function prepare() {
    specifiers = expandSpecifiers(root, options)
    const names = await sharedNames(root, specifiers)
    shims = new Map(specifiers.map((s) => [shimFileName(s), shimSource(s, names.get(s) ?? [])]))
  }

  return {
    name: 'shell:shared-libraries',
    configResolved(config) {
      root = config.root
      base = config.base
    },
    async buildStart() {
      await prepare()
    },
    resolveId(id) {
      return id === REGISTRY_MODULE ? `\0${REGISTRY_MODULE}` : null
    },
    load(id) {
      return id === `\0${REGISTRY_MODULE}` ? registrySource(specifiers) : null
    },
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const prefix = `${base}${SHIM_DIRECTORY}/`
        const url = request.url?.split('?')[0] ?? ''
        const shim = url.startsWith(prefix) ? shims.get(url.slice(prefix.length)) : undefined
        if (shim === undefined) return next()
        response.setHeader('Content-Type', 'text/javascript')
        response.end(shim)
      })
    },
    generateBundle() {
      for (const [fileName, source] of shims) {
        this.emitFile({ type: 'asset', fileName: `${SHIM_DIRECTORY}/${fileName}`, source })
      }
    },
    transformIndexHtml() {
      // FIRST IN <head>: an import map must be in place before any
      // module script runs, or the browser ignores it.
      return [
        {
          tag: 'script',
          attrs: { type: 'importmap' },
          children: JSON.stringify(importMap(specifiers, base), null, 2),
          injectTo: 'head-prepend',
        },
      ]
    },
  }
}
