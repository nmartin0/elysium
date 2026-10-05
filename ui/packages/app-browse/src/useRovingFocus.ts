import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

/**
 * One tab stop for a whole list, arrows to move inside it.
 *
 * WHAT IT COSTS WITHOUT THIS. Every result card holds a checkbox and a
 * title link, so a hundred results is two hundred Tab presses to reach
 * whatever follows the list. A keyboard user cannot get PAST the
 * results to the pagination below them without holding Tab down.
 *
 * WHY THE PATTERN FITS, which the roadmap entry got backwards. It said
 * our results are "cards with links, not a grid, so `role=\"grid\"`
 * without the full keyboard contract would be worse than native
 * semantics". The ARIA Authoring Practices Guide says the opposite:
 * "when data elements are links to more information, rather than
 * presenting them in a static table and including the links in the tab
 * sequence, implementing the grid pattern provides users with intuitive
 * and efficient keyboard navigation of the grid contents as well as a
 * shorter tab sequence" -- and its own first worked example is "Simple
 * List of Links".
 *
 * The second half of that entry stands, and is why this hook exists
 * rather than three `tabIndex` attributes: a PARTIAL contract is worse
 * than none. A list that takes focus and then does not answer Home,
 * End or the arrow keys has taken a working Tab sequence away and
 * given nothing back.
 *
 * SO THE WHOLE CONTRACT, from the APG's grid pattern:
 *
 *   ArrowDown / ArrowUp      previous and next row
 *   ArrowRight / ArrowLeft   previous and next cell WITHIN a row
 *   Home / End               first and last row
 *   Tab                      leaves the list entirely
 *
 * FOCUS FOLLOWS THE ROW, not the cell, when moving vertically. Moving
 * down from a checkbox lands on the next row's checkbox, which is what
 * makes selecting several rows in a column possible at all.
 */

export interface RovingFocus {
  /** Props for the list container. */
  containerProps: {
    role: 'grid'
    'aria-rowcount': number
    onKeyDown: (event: React.KeyboardEvent<HTMLElement>) => void
  }
  /** Props for one row, by its index. */
  rowProps: (row: number) => {
    role: 'row'
    'aria-rowindex': number
    ref: (node: HTMLElement | null) => void
  }
  /** Whether this cell is the single tab stop. */
  isTabStop: (row: number, cell: number) => boolean
  /** The focused position, for callers that want to reflect it. */
  active: { row: number; cell: number }
}

export function useRovingFocus(rowCount: number, cellsPerRow: number): RovingFocus {
  const [stored, setActive] = useState({ row: 0, cell: 0 })
  const rows = useRef(new Map<number, HTMLElement>())
  /**
   * MOVE FOCUS ONLY AFTER A KEY, never on render.
   *
   * An earlier shape focused whatever `active` pointed at in an effect
   * with `[active]`, which stole focus the moment results arrived --
   * typing in the search box, getting results, and losing the cursor
   * to the first card. The flag says "a key moved this", and only then
   * does the DOM follow.
   */
  const shouldFocus = useRef(false)

  /**
   * CLAMPED WHEN READ, not corrected in an effect.
   *
   * It used to clamp with a `setState` inside `useEffect` when
   * `rowCount` shrank, and oxlint refused it: "effects should
   * synchronize React with external systems". It was right -- this is
   * not synchronisation, it is a value derived from two others, and
   * deriving it needs no effect and no extra render.
   *
   * The case it handles is real: search again, get fewer results, and
   * the stored row points past the end so nothing is in the tab
   * sequence at all.
   */
  const active = useMemo(
    () => ({
      row: Math.min(stored.row, Math.max(0, rowCount - 1)),
      cell: stored.cell,
    }),
    // MEMOISED BECAUSE AN EFFECT DEPENDS ON IT. A fresh object each
    // render makes `[active]` change every render, so the focus effect
    // would run constantly rather than once per key.
    [stored, rowCount],
  )

  useEffect(() => {
    if (!shouldFocus.current) return
    shouldFocus.current = false
    const row = rows.current.get(active.row)
    if (!row) return
    const cells = row.querySelectorAll<HTMLElement>('[data-roving-cell]')
    cells[Math.min(active.cell, cells.length - 1)]?.focus()
  }, [active])

  const onKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLElement>) => {
      if (rowCount === 0) return
      const { row, cell } = active
      let next: { row: number; cell: number } | null = null

      if (event.key === 'ArrowDown') next = { row: Math.min(row + 1, rowCount - 1), cell }
      else if (event.key === 'ArrowUp') next = { row: Math.max(row - 1, 0), cell }
      else if (event.key === 'ArrowRight') {
        next = { row, cell: Math.min(cell + 1, cellsPerRow - 1) }
      } else if (event.key === 'ArrowLeft') next = { row, cell: Math.max(cell - 1, 0) }
      else if (event.key === 'Home') next = { row: 0, cell: 0 }
      else if (event.key === 'End') next = { row: rowCount - 1, cell: 0 }

      if (!next) return
      // THE DEFAULT IS A SCROLL. ArrowDown inside a long list would move
      // focus AND scroll the page, so the focused card leaves the
      // viewport it was just moved into.
      event.preventDefault()
      shouldFocus.current = true
      setActive(next)
    },
    [active, rowCount, cellsPerRow],
  )

  const rowProps = useCallback(
    (row: number) => ({
      role: 'row' as const,
      'aria-rowindex': row + 1,
      ref: (node: HTMLElement | null) => {
        if (node) rows.current.set(row, node)
        else rows.current.delete(row)
      },
    }),
    [],
  )

  return {
    containerProps: { role: 'grid', 'aria-rowcount': rowCount, onKeyDown },
    rowProps,
    isTabStop: (row: number, cell: number) => row === active.row && cell === active.cell,
    active,
  }
}
