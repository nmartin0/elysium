import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { MINIMUM_VISIBLE_MS, REVEAL_DELAY_MS, useSettledSpinner } from './useSettledSpinner'

beforeEach(() => {
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
})

const advance = (ms: number) => act(() => void vi.advanceTimersByTime(ms))

describe('rule one: a fast request produces no spinner at all', () => {
  /**
   * "Below about 100ms, showing progress is worse than showing
   * nothing, because the feedback itself becomes the disruption." Every
   * fetch in this application used to mount a spinner immediately.
   */

  it('shows nothing before the reveal delay', () => {
    const { result } = renderHook(() => useSettledSpinner(true))

    advance(REVEAL_DELAY_MS - 1)

    expect(result.current).toBe(false)
  })

  it('never shows one for a request that finishes first', () => {
    const { result, rerender } = renderHook(({ loading }) => useSettledSpinner(loading), {
      initialProps: { loading: true },
    })

    advance(90)
    rerender({ loading: false })
    advance(5_000)

    expect(result.current).toBe(false)
  })

  it('shows one for a request slow enough to need it', () => {
    const { result } = renderHook(() => useSettledSpinner(true))

    advance(REVEAL_DELAY_MS)

    expect(result.current).toBe(true)
  })
})

describe('rule two: once shown, it stays long enough to read', () => {
  /**
   * The rule that is easy to leave out. With a reveal delay alone, a
   * request finishing just after the threshold shows a spinner for a
   * few milliseconds -- "you have replaced a five-frame flash with a
   * two-frame flash, which is worse".
   */

  it('holds the spinner when the request finishes just after it appeared', () => {
    const { result, rerender } = renderHook(({ loading }) => useSettledSpinner(loading), {
      initialProps: { loading: true },
    })

    advance(REVEAL_DELAY_MS)
    expect(result.current).toBe(true)

    advance(30)
    rerender({ loading: false })

    expect(result.current).toBe(true)
  })

  it('releases it once the minimum visible time has passed', () => {
    const { result, rerender } = renderHook(({ loading }) => useSettledSpinner(loading), {
      initialProps: { loading: true },
    })

    advance(REVEAL_DELAY_MS)
    advance(30)
    rerender({ loading: false })
    advance(MINIMUM_VISIBLE_MS)

    expect(result.current).toBe(false)
  })

  it('does not hold a spinner that was already up long enough', () => {
    /** A slow request has shown its spinner for seconds; there is
     *  nothing to hold and the content should appear at once. */
    const { result, rerender } = renderHook(({ loading }) => useSettledSpinner(loading), {
      initialProps: { loading: true },
    })

    advance(REVEAL_DELAY_MS + MINIMUM_VISIBLE_MS + 1_000)
    rerender({ loading: false })

    expect(result.current).toBe(false)
  })
})

describe('the worst case is bounded', () => {
  it('never exceeds the delay plus the hold', () => {
    /** A request taking 210ms shows a spinner for 600. That is
     *  deliberate: a steady 600ms reads as the system working, where
     *  10ms reads as it glitching. */
    const { result, rerender } = renderHook(({ loading }) => useSettledSpinner(loading), {
      initialProps: { loading: true },
    })

    advance(REVEAL_DELAY_MS + 10)
    rerender({ loading: false })
    advance(MINIMUM_VISIBLE_MS)

    expect(result.current).toBe(false)
  })
})
