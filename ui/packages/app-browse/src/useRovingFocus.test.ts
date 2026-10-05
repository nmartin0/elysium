import { describe, expect, it } from 'vitest'
import { act, renderHook } from '@testing-library/react'

import { useRovingFocus } from './useRovingFocus'

/**
 * One tab stop for the whole list, arrows to move inside it.
 *
 * WHY THE PATTERN FITS, which the roadmap entry got backwards. It said
 * our results are "cards with links, not a grid", so the grid pattern
 * would be wrong. The ARIA Authoring Practices Guide says it is FOR
 * that case: "when data elements are links to more information...
 * implementing the grid pattern provides users with intuitive and
 * efficient keyboard navigation of the grid contents as well as a
 * shorter tab sequence", and its first worked example is "Simple List
 * of Links".
 *
 * The entry's second half is why this is a hook and not three
 * `tabIndex` attributes: a PARTIAL contract is worse than none. A list
 * that takes focus and then ignores Home, End or an arrow has removed
 * a working Tab sequence and given nothing back. So every key below is
 * tested, not just the two obvious ones.
 */

const keyEvent = (key: string) => {
  let defaultPrevented = false
  return {
    event: {
      key,
      preventDefault: () => {
        defaultPrevented = true
      },
    } as React.KeyboardEvent<HTMLElement>,
    wasPrevented: () => defaultPrevented,
  }
}

const press = (result: { current: ReturnType<typeof useRovingFocus> }, key: string) => {
  const { event, wasPrevented } = keyEvent(key)
  act(() => {
    result.current.containerProps.onKeyDown(event)
  })
  return wasPrevented()
}

describe('the whole keyboard contract', () => {
  it('starts on the first cell of the first row', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    expect(result.current.active).toEqual({ row: 0, cell: 0 })
    expect(result.current.isTabStop(0, 0)).toBe(true)
  })

  it('ArrowDown and ArrowUp move between rows', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    press(result, 'ArrowDown')
    expect(result.current.active.row).toBe(1)

    press(result, 'ArrowUp')
    expect(result.current.active.row).toBe(0)
  })

  it('ArrowRight and ArrowLeft move between cells of one row', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    press(result, 'ArrowRight')
    expect(result.current.active).toEqual({ row: 0, cell: 1 })

    press(result, 'ArrowLeft')
    expect(result.current.active).toEqual({ row: 0, cell: 0 })
  })

  it('keeps the column when moving down, so a column can be selected', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    press(result, 'ArrowRight')
    press(result, 'ArrowDown')

    expect(result.current.active).toEqual({ row: 1, cell: 1 })
  })

  it('Home and End reach the ends', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    press(result, 'End')
    expect(result.current.active).toEqual({ row: 4, cell: 0 })

    press(result, 'Home')
    expect(result.current.active).toEqual({ row: 0, cell: 0 })
  })

  it('stops at the ends rather than wrapping', () => {
    /** Wrapping is a choice the APG allows and this list does not make:
     * a hundred results wrapping to the top looks like nothing
     * happened. */
    const { result } = renderHook(() => useRovingFocus(3, 2))

    press(result, 'ArrowUp')
    expect(result.current.active.row).toBe(0)

    press(result, 'End')
    press(result, 'ArrowDown')
    expect(result.current.active.row).toBe(2)
  })

  it('prevents the default, because ArrowDown also scrolls', () => {
    /** Without this, focus moves AND the page scrolls, so the card just
     * focused leaves the viewport. */
    const { result } = renderHook(() => useRovingFocus(5, 2))

    expect(press(result, 'ArrowDown')).toBe(true)
  })

  it('ignores keys that are not part of the contract', () => {
    const { result } = renderHook(() => useRovingFocus(5, 2))

    expect(press(result, 'a')).toBe(false)
    expect(result.current.active).toEqual({ row: 0, cell: 0 })
  })

  it('does nothing at all on an empty list', () => {
    const { result } = renderHook(() => useRovingFocus(0, 2))

    expect(press(result, 'ArrowDown')).toBe(false)
  })
})

describe('exactly one tab stop', () => {
  it('only the active cell is in the tab sequence', () => {
    const { result } = renderHook(() => useRovingFocus(3, 2))

    const stops = [0, 1, 2].flatMap((row) => [0, 1].filter((cell) => result.current.isTabStop(row, cell)))

    expect(stops).toHaveLength(1)
  })

  it('and it follows the arrows', () => {
    const { result } = renderHook(() => useRovingFocus(3, 2))

    press(result, 'ArrowDown')

    expect(result.current.isTabStop(0, 0)).toBe(false)
    expect(result.current.isTabStop(1, 0)).toBe(true)
  })
})

describe('the list changing under it', () => {
  it('a shorter list does not leave the active row past the end', () => {
    /** Search again, get fewer results, and `active` pointed at a row
     * that no longer exists -- so Tab reached nothing. */
    const { result, rerender } = renderHook(({ rows }) => useRovingFocus(rows, 2), {
      initialProps: { rows: 10 },
    })

    press(result, 'End')
    expect(result.current.active.row).toBe(9)

    rerender({ rows: 3 })

    expect(result.current.active.row).toBe(2)
  })

  it('an emptied list collapses to row zero', () => {
    const { result, rerender } = renderHook(({ rows }) => useRovingFocus(rows, 2), {
      initialProps: { rows: 5 },
    })

    press(result, 'End')
    rerender({ rows: 0 })

    expect(result.current.active.row).toBe(0)
  })
})

describe('what it tells assistive technology', () => {
  it('the container is a grid and says how many rows', () => {
    const { result } = renderHook(() => useRovingFocus(42, 2))

    expect(result.current.containerProps.role).toBe('grid')
    expect(result.current.containerProps['aria-rowcount']).toBe(42)
  })

  it('rows are rows, numbered from one', () => {
    const { result } = renderHook(() => useRovingFocus(3, 2))

    expect(result.current.rowProps(0).role).toBe('row')
    expect(result.current.rowProps(0)['aria-rowindex']).toBe(1)
    expect(result.current.rowProps(2)['aria-rowindex']).toBe(3)
  })
})
