/**
 * Building a module's bundle, and building every module with the page.
 *
 * `moduleConfig` is the Vite config a module's own `vite.config.ts`
 * returns: one ES module exporting `activate` (@shell/core/moduleLoader),
 * plus its stylesheet, with the page's shared libraries left as bare
 * imports so the import map sends them to the page's copies
 * (sharedLibraries.ts). Everything else the module imports is bundled
 * into it -- its private libraries.
 *
 * A DEEP IMPORT OF A SHARED LIBRARY IS REFUSED, not bundled. A module
 * writing `@blueprintjs/core/lib/esm/...` would get a private second copy
 * of part of a library whose state the page owns -- the failure the
 * import map exists to prevent, arriving by a side door. The build stops
 * and names the import.
 *
 * `builtModules` is the plugin a host page adds so that `vite build`
 * builds each module too, and the dev server rebuilds each one on save
 * (decided 21 October: development loads the built bundle as production
 * does -- one path).
 */
import { build, type Plugin, type UserConfig } from 'vite'

export interface ModuleBuildOptions {
  /** The module's folder. */
  root: string
  /** Its entry, relative to `root`: the file exporting `activate`. */
  entry: string
  /** The page's shared libraries and packages (sharedLibraries.ts). */
  libraries: readonly string[]
  packages: readonly string[]
  /** Where the bundle goes, relative to `root`. */
  outDir?: string
}

/** Whether `id` is something the page shares, so the bundle leaves it bare. */
export function isShared(id: string, libraries: readonly string[], packages: readonly string[]): boolean {
  return libraries.includes(id) || packages.some((pkg) => id.startsWith(`${pkg}/`))
}

/** The npm package a specifier belongs to: `react` for `react/jsx-runtime`. */
export function packageOf(specifier: string): string {
  const parts = specifier.split('/')
  return specifier.startsWith('@') ? parts.slice(0, 2).join('/') : (parts[0] ?? specifier)
}

/**
 * The shared package an import would take a PRIVATE copy of, if any: one
 * whose package the page shares, by a specifier the page does not.
 */
export function privateCopyOfShared(
  id: string,
  libraries: readonly string[],
  packages: readonly string[],
): string | undefined {
  if (isShared(id, libraries, packages)) return undefined
  const sharedPackages = new Set([...libraries.map(packageOf), ...packages])
  const pkg = packageOf(id)
  return sharedPackages.has(pkg) ? pkg : undefined
}

export function moduleConfig(options: ModuleBuildOptions): UserConfig {
  const { libraries, packages } = options
  return {
    root: options.root,
    logLevel: 'warn',
    // A library build does not define this, and React reads it.
    define: { 'process.env.NODE_ENV': JSON.stringify('production') },
    oxc: { jsx: { runtime: 'automatic' } },
    plugins: [
      {
        name: 'shell:no-deep-shared-imports',
        enforce: 'pre',
        resolveId(id) {
          const pkg = privateCopyOfShared(id, libraries, packages)
          if (pkg !== undefined) {
            throw new Error(
              `${id} is part of ${pkg}, which the page shares, but not an entry it shares; ` +
                'import from a shared entry, or the module would bundle a second copy of part of it',
            )
          }
          return null
        },
      },
    ],
    build: {
      outDir: options.outDir ?? 'dist',
      emptyOutDir: true,
      lib: { entry: options.entry, formats: ['es'], fileName: () => 'index.js', cssFileName: 'index' },
      rolldownOptions: { external: (id) => isShared(id, libraries, packages) },
    },
  }
}

export interface BuiltModulesOptions {
  /** Each module's `vite.config.ts`. */
  configs: readonly string[]
}

/** Builds each module with the page, and rebuilds each on save in dev. */
export function builtModules(options: BuiltModulesOptions): Plugin {
  let command: 'build' | 'serve' = 'serve'
  let watchers: Awaited<ReturnType<typeof build>>[] = []
  return {
    name: 'shell:built-modules',
    configResolved(config) {
      command = config.command
    },
    async closeBundle() {
      if (command !== 'build') return
      for (const configFile of options.configs) await build({ configFile })
    },
    async configureServer() {
      // NOT UNDER TEST RUNNERS: a test that starts a dev server must not
      // start a module build in the background with it.
      if (process.env.VITEST) return
      watchers = await Promise.all(options.configs.map((configFile) => build({ configFile, build: { watch: {} } })))
    },
    // CLOSED WITH THE DEV SERVER: Vite runs `buildEnd` when it closes, in
    // middleware mode too, where there is no HTTP server to listen to.
    async buildEnd() {
      if (command !== 'serve') return
      await Promise.all(watchers.map((watcher) => ('close' in watcher ? watcher.close() : undefined)))
      watchers = []
    },
  }
}
