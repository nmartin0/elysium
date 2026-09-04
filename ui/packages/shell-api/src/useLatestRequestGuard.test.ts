import { describe, it, expect } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useLatestRequestGuard } from './useLatestRequestGuard'

// A real, isolated test for this hook's own real behavior, in
// addition to (not instead of) the two, real, existing consumer-level
// tests already covering it indirectly (ObjectSearchPanel's own "a
// SLOWER, earlier request..." test, ObjectDetailPanel's own "a
// SLOWER response for the FIRST object..." test) -- a genuine,
// additional benefit of extracting this hook at all: it's now
// directly testable in isolation, not just observable through two
// real components' own, much larger integration tests.

describe('useLatestRequestGuard', () => {
  it('startRequest() returns real, distinct, incrementing ids', () => {
    const { result } = renderHook(() => useLatestRequestGuard())

    let first: number
    let second: number
    let third: number
    act(() => {
      first = result.current.startRequest()
      second = result.current.startRequest()
      third = result.current.startRequest()
    })

    expect(first!).toBe(1)
    expect(second!).toBe(2)
    expect(third!).toBe(3)
  })

  it('isStale() is false for the request that is genuinely still the latest one', () => {
    const { result } = renderHook(() => useLatestRequestGuard())

    let requestId: number
    act(() => {
      requestId = result.current.startRequest()
    })

    expect(result.current.isStale(requestId!)).toBe(false)
  })

  it('isStale() becomes true for an older request the MOMENT a newer one starts -- the real, whole point of this hook', () => {
    const { result } = renderHook(() => useLatestRequestGuard())

    let olderRequestId: number
    act(() => {
      olderRequestId = result.current.startRequest()
    })
    expect(result.current.isStale(olderRequestId!)).toBe(false)

    act(() => {
      result.current.startRequest()
    })

    // The older one is now genuinely stale -- a real, later request
    // has since started, exactly the real scenario this hook exists
    // to detect (a slower, earlier response arriving after a faster,
    // later one already resolved).
    expect(result.current.isStale(olderRequestId!)).toBe(true)
  })

  it("the guard's own state persists across a real re-render -- backed by useRef, not useState, deliberately: this hook must never itself trigger a re-render just by tracking request ids", () => {
    const { result, rerender } = renderHook(() => useLatestRequestGuard())

    let requestId: number
    act(() => {
      requestId = result.current.startRequest()
    })

    rerender()

    expect(result.current.isStale(requestId!)).toBe(false)
  })
})
