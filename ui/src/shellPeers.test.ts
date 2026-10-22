/**
 * EVERY LIBRARY THE SHELL TAKES AS A PEER IS ONE COPY IN THE PAGE.
 *
 * @shell/core is linked in by `file:` from ../shell, whose own
 * node_modules holds copies of its peers for its own tests. Vite resolves
 * an import from the file's location, so without `resolve.dedupe` the
 * frame would bundle the shell's copy beside the page's. Measured when
 * Blueprint became a peer (step 1.3): the build held two Blueprints, and
 * the frame's palette would have had an overlay stack of its own.
 */
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

const UI = join(import.meta.dirname, '..')
const peers = Object.keys(
  (
    JSON.parse(readFileSync(join(UI, '..', 'shell', 'core', 'package.json'), 'utf8')) as {
      peerDependencies: Record<string, string>
    }
  ).peerDependencies,
)
const deduped = (file: string) => {
  const list = /dedupe:\s*\[([^\]]*)\]/.exec(readFileSync(join(UI, file), 'utf8'))?.[1] ?? ''
  return [...list.matchAll(/'([^']+)'/g)].map((m) => m[1])
}

describe("the shell's peers are deduplicated", () => {
  it('reads the peers, so an empty list cannot pass', () => {
    expect(peers).toEqual(expect.arrayContaining(['react', '@blueprintjs/core']))
  })

  it.each(['vite.config.ts', 'packages/app-schema/vitest.config.ts'])('%s dedupes every one', (file) => {
    expect(peers.filter((peer) => !deduped(file).includes(peer))).toEqual([])
  })
})
