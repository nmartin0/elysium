/**
 * DataTable -- every table in Elysium, one way (DEV_UI 9.3, 9.4).
 *
 * SEVENTEEN TABLES, FOUR LOOKS. They were Blueprint's HTMLTable with
 * whatever props the author reached for -- `compact striped`,
 * `striped interactive`, `compact` alone -- plus two bare <table>s. The
 * design decided one answer and nothing applied it:
 *
 *   HAIRLINES AND HOVER, NOT ZEBRA (9.4, specimen D3): rules at 45% of
 *   the border colour and an accent wash on hover. "Zebra adds a second
 *   background that muddies a navy canvas and fights the surface steps
 *   that carry elevation" -- so there is no `striped` prop to reach for.
 *
 *   DENSITY IS THE READER'S, NOT THE TABLE'S (9.3): middle (~38px rows)
 *   by default, compact (~30px) one click away in the user menu, roomy
 *   (~48px) for touch, persisted per user. So there is no `compact`
 *   prop either; the row height comes from the preference.
 *
 *   A STICKY HEADER, always. Numbers RIGHT-ALIGNED: give their cells,
 *   header and body alike, `className="data-table__num"` -- written
 *   out rather than imported as a constant, so the stylesheet check
 *   that every styled class is rendered somewhere can see it.
 *
 * A WRAPPER OVER Blueprint's HTMLTable rather than a table of our own:
 * the point is the reduced surface -- "the gained consistency of
 * reducing the used API surface" (BLOCKING's UI-kit item) -- not
 * replacing a component that renders a <table> correctly already.
 */

import { HTMLTable } from '@blueprintjs/core'
import type { HTMLTableProps } from '@blueprintjs/core'

type DataTableProps = Omit<HTMLTableProps, 'striped' | 'compact' | 'bordered'>

export default function DataTable({ className, ...rest }: DataTableProps) {
  return <HTMLTable className={className ? `data-table ${className}` : 'data-table'} {...rest} />
}

export type SortDirection = 'asc' | 'desc' | null

/**
 * A sortable column's header (DEV_UI 9.4): "Sort indicator on the
 * active column, subtle on the other sortable ones."
 *
 * A BUTTON INSIDE THE <th>, with aria-sort on the header itself -- the
 * APG's sortable-table pattern, so a screen reader hears both that the
 * column can be sorted and how it is sorted now. Clicking cycles
 * ascending, descending, unsorted; the caller owns the order.
 */
export function SortableHeader({
  label,
  direction,
  onSort,
  numeric = false,
}: {
  label: string
  direction: SortDirection
  onSort: (next: SortDirection) => void
  numeric?: boolean
}) {
  const next: SortDirection = direction === null ? 'asc' : direction === 'asc' ? 'desc' : null
  const sort = direction === 'asc' ? 'ascending' : direction === 'desc' ? 'descending' : 'none'
  return (
    <th aria-sort={sort} className={numeric ? 'data-table__num' : undefined}>
      <button type="button" className="data-table__sort" onClick={() => onSort(next)}>
        {label}
        <span
          className={direction ? 'data-table__sort-mark data-table__sort-mark--active' : 'data-table__sort-mark'}
          aria-hidden="true"
        >
          {direction === 'asc' ? '↑' : direction === 'desc' ? '↓' : '↕'}
        </span>
      </button>
    </th>
  )
}
