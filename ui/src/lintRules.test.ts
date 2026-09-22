/**
 * The linter can see a broken hook -- measured, not assumed.
 *
 * AUDIT-10: oxlint ran NO React hook rules. A conditional useState scored
 * "0 warnings and 0 errors", so every "lint passes" was blind to the most
 * common React bug there is. This runs the real oxlint, with this
 * project's own configuration, over a planted violation.
 */

import { spawnSync } from 'node:child_process'
import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve } from 'node:path'

import { afterAll, describe, expect, it } from 'vitest'

const dir = mkdtempSync(join(tmpdir(), 'hook-probe-'))
afterAll(() => rmSync(dir, { recursive: true, force: true }))

function lint(source: string) {
  const file = join(dir, 'Probe.tsx')
  writeFileSync(file, source)
  const oxlint = resolve(process.cwd(), 'node_modules/.bin/oxlint')
  const config = resolve(process.cwd(), '.oxlintrc.json')
  const result = spawnSync(oxlint, ['--deny-warnings', '-c', config, file], { encoding: 'utf8' })
  return { status: result.status, output: `${result.stdout}${result.stderr}` }
}

describe('the React hook rules run', () => {
  it('rejects a hook called conditionally', () => {
    const { status, output } = lint(`import { useState } from 'react'
export function Probe({ on }: { on: boolean }) {
  if (on) {
    const [value] = useState(0)
    return <span>{value}</span>
  }
  return null
}
`)

    expect(output).toContain('rules-of-hooks')
    expect(status).not.toBe(0)
  })

  it('rejects an effect missing a dependency', () => {
    const { status, output } = lint(`import { useEffect } from 'react'
export function Probe({ id }: { id: string }) {
  useEffect(() => {
    console.log(id)
  }, [])
  return null
}
`)

    expect(output).toContain('exhaustive-deps')
    expect(status).not.toBe(0)
  })

  it('accepts the same hook called unconditionally', () => {
    // THE CONTROL INSIDE THE TEST: without it, a linter failing for any
    // reason at all -- a bad path, a broken config -- would pass above.
    const { status } = lint(`import { useState } from 'react'
export function Probe() {
  const [value] = useState(0)
  return <span>{value}</span>
}
`)

    expect(status).toBe(0)
  })
})
