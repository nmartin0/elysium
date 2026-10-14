import { describe, expect, it } from 'vitest'
import { render } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import DataTable from './DataTable'

const CSS = readFileSync(resolve(process.cwd(), 'packages/shell-api/src/index.css'), 'utf8')

describe('DataTable', () => {
  it('is a real table carrying the one class every table is styled by', () => {
    const { container } = render(
      <DataTable className="extra">
        <tbody>
          <tr>
            <td className="data-table__num">12</td>
          </tr>
        </tbody>
      </DataTable>,
    )
    const table = container.querySelector('table')

    expect(table?.classList.contains('data-table')).toBe(true)
    expect(table?.classList.contains('extra')).toBe(true)
    // NO ZEBRA, whatever is passed (DEV_UI 9.4): the prop does not exist.
    expect(table?.classList.contains('bp6-html-table-striped')).toBe(false)
  })

  it('every DataTable row takes the reader density, and the header sticks', () => {
    // Read from the stylesheet: jsdom computes no layout.
    const cell = /\.data-table th,\s*\n\s*\.data-table td \{([^}]*)\}/.exec(CSS)?.[1] ?? ''
    const head = /\.data-table thead th \{([^}]*)\}/.exec(CSS)?.[1] ?? ''

    expect(cell).toMatch(/height:\s*var\(--row-height\)/)
    expect(head).toMatch(/position:\s*sticky/)
  })

  it('numbers are right-aligned', () => {
    expect(CSS).toMatch(/\.data-table \.data-table__num \{[^}]*text-align:\s*right/)
  })
})
