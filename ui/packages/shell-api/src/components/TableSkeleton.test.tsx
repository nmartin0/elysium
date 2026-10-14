import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import TableSkeleton from './TableSkeleton'

const CSS = readFileSync(resolve(process.cwd(), 'packages/shell-api/src/index.css'), 'utf8')

describe('TableSkeleton (DEV_UI 9.7, E1)', () => {
  it('sketches the rows and columns it is given, hidden from assistive technology', () => {
    const { container } = render(<TableSkeleton rows={3} columns={5} />)
    const skeleton = container.querySelector('.table-skeleton')!

    expect(skeleton.getAttribute('aria-hidden')).toBe('true')
    expect(skeleton.querySelectorAll('.table-skeleton__row')).toHaveLength(3)
    expect(skeleton.querySelectorAll('.table-skeleton__cell')).toHaveLength(15)
  })

  it('waits a second before showing, and does not pulse for reduced motion', () => {
    // "Over 1s: a skeleton" -- a faster answer replaces it unseen.
    expect(/\.table-skeleton \{[^}]*animation:[^;]*1000ms/.exec(CSS)).not.toBeNull()
    expect(CSS).toMatch(/prefers-reduced-motion: reduce\) \{\s*\.table-skeleton__cell \{\s*animation: none/)
  })
})
