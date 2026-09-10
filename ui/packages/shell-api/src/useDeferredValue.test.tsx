import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, fireEvent, act } from '@testing-library/react'

import { SETTLE_MS, useDeferredWrite } from './useDeferredValue'

/**
 * Keeps a control instant while its expensive consequence waits.
 *
 * Typing in Schema's filter wrote to the URL per character -- a router
 * navigation each time, re-rendering the whole panel. The box kept up
 * because it holds local state, but everything around it lurched,
 * which reads as lag and is worse when deleting because a held
 * backspace costs the same per repeat.
 */

function Harness({ write, external }: { write: (v: string) => void; external?: string }) {
  const [value, set, adopt] = useDeferredWrite('', write)
  return (
    <>
      <input value={value} onChange={(e) => set(e.target.value)} />
      <button onClick={() => adopt(external ?? '')}>adopt</button>
    </>
  )
}

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true })
})

afterEach(() => {
  vi.useRealTimers()
})

describe('useDeferredWrite', () => {
  it('updates the visible value immediately', () => {
    // The whole point: the control never waits.
    render(<Harness write={vi.fn()} />)
    const box = screen.getByRole('textbox')

    fireEvent.change(box, { target: { value: 'C' } })

    expect(box).toHaveValue('C')
  })

  it('writes once for a burst of keystrokes, not once each', () => {
    const write = vi.fn()
    render(<Harness write={write} />)
    const box = screen.getByRole('textbox')

    for (const v of ['C', 'Cu', 'Cus', 'Cust']) {
      fireEvent.change(box, { target: { value: v } })
    }
    expect(write).not.toHaveBeenCalled()

    act(() => {
      vi.advanceTimersByTime(SETTLE_MS)
    })

    expect(write).toHaveBeenCalledTimes(1)
    expect(write).toHaveBeenCalledWith('Cust')
  })

  it('cancels a pending write when a value arrives from outside', () => {
    /**
     * Pressing Back while a keystroke is still settling must not have
     * that keystroke land afterwards and undo the navigation.
     */
    const write = vi.fn()
    render(<Harness write={write} external="elsewhere" />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'half' } })

    fireEvent.click(screen.getByText('adopt'))
    act(() => {
      vi.advanceTimersByTime(SETTLE_MS * 2)
    })

    expect(write).not.toHaveBeenCalled()
    expect(screen.getByRole('textbox')).toHaveValue('elsewhere')
  })

  it('does not write after unmount', () => {
    // A timer outliving its component writes to a router that has
    // moved on.
    const write = vi.fn()
    const { unmount } = render(<Harness write={write} />)
    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'x' } })

    unmount()
    act(() => {
      vi.advanceTimersByTime(SETTLE_MS * 2)
    })

    expect(write).not.toHaveBeenCalled()
  })

  it('uses the latest callback, not the one from the first render', () => {
    // Callers pass inline arrows, which are new every render. Holding
    // the first would write using stale state -- here, the wrong tab.
    const first = vi.fn()
    const second = vi.fn()
    const { rerender } = render(<Harness write={first} />)
    rerender(<Harness write={second} />)

    fireEvent.change(screen.getByRole('textbox'), { target: { value: 'x' } })
    act(() => {
      vi.advanceTimersByTime(SETTLE_MS)
    })

    expect(first).not.toHaveBeenCalled()
    expect(second).toHaveBeenCalledWith('x')
  })
})
