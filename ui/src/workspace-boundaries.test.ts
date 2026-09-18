// workspace-boundaries.test.ts -- structural tests on the workspace
// itself, not any one package's runtime behavior. Reads the real
// package.json files from disk and asserts on their actual content --
// this is what actually enforces "sub-apps depend on shell-api and
// NOTHING else in the workspace" as an ongoing, checked property, not
// just something true by inspection the day this was written. The
// SAME kind of property .oxlintrc.json's own no-restricted-imports
// rule enforces at the import-statement level -- this file checks it
// one layer up, at the package-dependency-declaration level.
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync, readdirSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const UI_ROOT = path.resolve(__dirname, '..')

// The real, minimal shape this file actually reads out of a
// package.json -- not the full, real npm package.json schema (which
// has dozens of optional fields this file never touches), matching
// this project's own established "don't invent a narrower or wider
// type than what's actually used" discipline elsewhere (see e.g.
// Shell.tsx's own VisibleApp). Every field genuinely optional here --
// a real package.json may omit dependencies/workspaces/exports
// entirely, and every call site below already, correctly guards for
// that with `|| {}` / `|| []`.
interface PackageJson {
  dependencies?: Record<string, string>
  workspaces?: string[]
  exports?: Record<string, string>
}

function readPackageJson(relativePath: string): PackageJson {
  return JSON.parse(readFileSync(path.join(UI_ROOT, relativePath, 'package.json'), 'utf-8')) as PackageJson
}

const SUB_APPS = ['packages/app-query', 'packages/app-browse', 'packages/app-admin']

describe('every sub-app depends on @elysium/shell-api and nothing else in the workspace', () => {
  it.each(SUB_APPS)('%s declares exactly @elysium/shell-api among its @elysium/* dependencies', (pkgDir) => {
    const pkg = readPackageJson(pkgDir)
    const elysiumDeps = Object.keys(pkg.dependencies || {}).filter((name) => name.startsWith('@elysium/'))
    expect(elysiumDeps).toEqual(['@elysium/shell-api'])
  })
})

describe('shell-api is the base layer -- depends on no other workspace package', () => {
  it('declares no @elysium/* dependencies at all', () => {
    const pkg = readPackageJson('packages/shell-api')
    const elysiumDeps = Object.keys(pkg.dependencies || {}).filter((name) => name.startsWith('@elysium/'))
    expect(elysiumDeps).toEqual([])
  })
})

describe('every declared export actually points to a real file on disk', () => {
  const allPackages = ['packages/shell-api', ...SUB_APPS]

  it.each(allPackages)('%s has no stale exports entries', (pkgDir) => {
    const pkg = readPackageJson(pkgDir)
    for (const [subpath, target] of Object.entries(pkg.exports || {})) {
      const fullPath = path.join(UI_ROOT, pkgDir, target)
      expect(existsSync(fullPath), `${pkgDir}'s exports["${subpath}"] -> ${target} does not exist`).toBe(true)
    }
  })
})

describe('the root package.json correctly declares the workspace', () => {
  it('lists packages/* as a workspace', () => {
    const pkg = readPackageJson('.')
    expect(pkg.workspaces).toContain('packages/*')
  })

  it('depends on every real sub-app and shell-api package by name', () => {
    const pkg = readPackageJson('.')
    expect(Object.keys(pkg.dependencies || {})).toEqual(
      expect.arrayContaining(['@elysium/shell-api', '@elysium/app-query', '@elysium/app-browse', '@elysium/app-admin']),
    )
  })
})

describe('package layering', () => {
  // "Structure your packages in layers: shared utilities at the
  // bottom, applications at the top." A sub-app importing from
  // another sub-app inverts that, and it is not hypothetical here:
  // app-schema imported its core ontology types from app-browse
  // because that is where they happened to be written first.
  //
  // Nothing caught it. The backend has import contracts enforcing the
  // same rule; this is the frontend's.

  const packagesDir = path.join(UI_ROOT, 'packages')
  const subAppDirs = readdirSync(packagesDir).filter((name) => name.startsWith('app-'))

  it('has more than one sub-app, or this check proves nothing', () => {
    expect(subAppDirs.length).toBeGreaterThan(1)
  })

  it('no sub-app imports from another sub-app', () => {
    const offenders: string[] = []

    for (const dir of subAppDirs) {
      const srcDir = path.join(packagesDir, dir, 'src')
      for (const file of readdirSync(srcDir)) {
        if (!file.endsWith('.ts') && !file.endsWith('.tsx')) continue
        const source = readFileSync(path.join(srcDir, file), 'utf8')
        for (const other of subAppDirs) {
          if (other === dir) continue
          if (source.includes(`@elysium/${other}`)) {
            offenders.push(`${dir}/${file} imports @elysium/${other}`)
          }
        }
      }
    }

    expect(offenders).toEqual([])
  })

  it('shell-api imports no sub-app', () => {
    // The other direction, and the worse one: the shared layer
    // depending upward would make the layering circular rather than
    // merely inverted.
    const srcDir = path.join(packagesDir, 'shell-api', 'src')

    function walk(dir: string): string[] {
      return readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
        entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)],
      )
    }

    const offenders = walk(srcDir).filter(
      (path) => (path.endsWith('.ts') || path.endsWith('.tsx')) && readFileSync(path, 'utf8').includes('@elysium/app-'),
    )

    expect(offenders).toEqual([])
  })
})

describe('every sub-app reads the same way', () => {
  it('puts its view selector in the pane, not a tab strip in the canvas', () => {
    /**
     * Consistency is the whole argument for the shared selector. A
     * shell where one sub-app reads left-to-right and another reads
     * left, then up, then down costs a decision on every arrival --
     * the mental model has to be rebuilt rather than reused.
     *
     * Browse kept a Blueprint Tabs strip for two rounds after Schema
     * and Admin moved, and nothing said so.
     */
    const panels = [
      'packages/app-browse/src/ObjectSearchPanel.tsx',
      'packages/app-schema/src/SchemaPanel.tsx',
      'packages/app-admin/src/AdminPanel.tsx',
    ]

    for (const panel of panels) {
      const source = readFileSync(path.resolve(__dirname, '..', panel), 'utf8')
      expect(source, `${panel} should use the shared ViewSelector`).toMatch(/<ViewSelector/)
      expect(source, `${panel} should not have its own tab strip`).not.toMatch(/<Tabs\b/)
    }
  })
})
