/**
 * useDeferredWrite -- keep a control instant while its expensive
 * consequence waits.
 *
 * Typing in a filter that writes to the URL costs a router navigation
 * per character, and the panel re-renders on each one. The box keeps
 * up, because it holds local state, but everything around it lurches
 * -- which reads as lag, and is worse when deleting because a
 * backspace costs the same as a keystroke and people hold the key
 * down.
 *
 * So the caller gets two things: a value that updates immediately, for
 * the control to show, and a callback that fires once the typing
 * settles.
 *
 * 300ms, matching the debounce Browse already used for its search --
 * one number for "the user has stopped typing", not two that drift.
 *
 * NOT React's own useDeferredValue. That defers RENDERING under
 * concurrent scheduling; this defers an effect with its own cost, and
 * it needs a timer rather than a priority hint.
 */

import { useCallback, useEffect, useRef, useState } from 'react'

export const SETTLE_MS = 300

export function useDeferredWrite(
  initial: string,
  write: (value: string) => void,
): [string, (value: string) => void, (value: string) => void] {
  const [value, setValue] = useState(initial)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)
  // Held in a ref so a caller passing an inline arrow does not restart
  // the timer on every render.
  const latestWrite = useRef(write)
  latestWrite.current = write

  const set = useCallback((next: string) => {
    setValue(next)
    if (timer.current !== null) clearTimeout(timer.current)
    timer.current = setTimeout(() => {
      timer.current = null
      latestWrite.current(next)
    }, SETTLE_MS)
  }, [])

  /**
   * Adopts a value from outside, cancelling any pending write.
   *
   * For navigation: pressing Back while a keystroke is still settling
   * must not have that keystroke land afterwards and undo the
   * navigation.
   */
  const adopt = useCallback((next: string) => {
    if (timer.current !== null) {
      clearTimeout(timer.current)
      timer.current = null
    }
    setValue(next)
  }, [])

  // A pending write must not fire after unmount.
  useEffect(() => () => {
    if (timer.current !== null) clearTimeout(timer.current)
  }, [])

  return [value, set, adopt]
}
