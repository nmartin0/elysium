import { describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import DataTable, { SortableHeader, type SortDirection } from './DataTable'

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

describe('SortableHeader (DEV_UI 9.4)', () => {
  const header = (direction: SortDirection, onSort = vi.fn()) =>
    render(
      <table>
        <thead>
          <tr>
            <SortableHeader label="Amount" direction={direction} onSort={onSort} numeric />
          </tr>
        </thead>
      </table>,
    )

  it('says how the column is sorted, to a screen reader as well as the eye', () => {
    header('desc')

    expect(screen.getByRole('columnheader').getAttribute('aria-sort')).toBe('descending')
    expect(screen.getByRole('columnheader').classList.contains('data-table__num')).toBe(true)
  })

  it('an unsorted column says none, and is still a control', () => {
    header(null)

    expect(screen.getByRole('columnheader').getAttribute('aria-sort')).toBe('none')
    expect(screen.getByRole('button', { name: /Amount/ })).toBeInTheDocument()
  })

  it.each([
    [null, 'asc'],
    ['asc', 'desc'],
    ['desc', null],
  ] as const)('a click from %s asks for %s', (from, to) => {
    const onSort = vi.fn()
    header(from, onSort)

    fireEvent.click(screen.getByRole('button', { name: /Amount/ }))

    expect(onSort).toHaveBeenCalledWith(to)
  })
})
