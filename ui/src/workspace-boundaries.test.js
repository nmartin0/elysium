// workspace-boundaries.test.js -- structural tests on the workspace
// itself, not any one package's runtime behavior. Reads the real
// package.json files from disk and asserts on their actual content --
// this is what actually enforces "sub-apps depend on shell-api and
// NOTHING else in the workspace" as an ongoing, checked property, not
// just something true by inspection the day this was written. The
// SAME kind of property .oxlintrc.json's own no-restricted-imports
// rule enforces at the import-statement level -- this file checks it
// one layer up, at the package-dependency-declaration level.
import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const UI_ROOT = path.resolve(__dirname, '..')

function readPackageJson(relativePath) {
  return JSON.parse(readFileSync(path.join(UI_ROOT, relativePath, 'package.json'), 'utf-8'))
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
    expect(Object.keys(pkg.dependencies)).toEqual(
      expect.arrayContaining(['@elysium/shell-api', '@elysium/app-query', '@elysium/app-browse', '@elysium/app-admin']),
    )
  })
})
