import { useEffect, useRef, useState } from 'react'

/**
 * Whether a spinner should be on screen right now.
 *
 * THE PROBLEM, AND IT IS EVERY FETCH IN THIS APPLICATION. Nothing
 * delays a loading indicator anywhere: `AsyncPanel` returns a
 * `<Spinner />` the instant its data is null, so a request answering in
 * 90ms mounts a spinner, paints a few frames and unmounts it. Nobody
 * perceives that as loading. They perceive the screen FLINCHING.
 *
 * TWO RULES, AND ONE ALONE IS NOT ENOUGH.
 *
 * The first is a reveal delay. Nielsen's response-time limits put 0.1s
 * as the threshold below which an action feels instantaneous, and the
 * implication most implementations miss is that "below about 100ms,
 * showing progress is worse than showing nothing, because the feedback
 * itself becomes the disruption". The sources cluster on 200-300ms;
 * 200 is taken here because Elysium's reads come from a local mirror
 * and are usually fast, so a longer delay would suppress the spinner
 * on requests that genuinely do need one.
 *
 * The second is a minimum visible time, and it is the one that is easy
 * to leave out. "Say your reveal delay is 140ms and the request
 * finishes at 170ms. Without a second rule, the spinner appears for 30
 * milliseconds. You have replaced a five-frame flash with a two-frame
 * flash, which is worse." Once shown, it stays for 400ms.
 *
 * SO THE WORST CASE IS 600ms OF SPINNER for a request that took 210.
 * That is deliberate: a steady 600ms reads as the system working,
 * where 10ms reads as the system glitching, and the second costs more
 * trust than the first costs time.
 */

/** Below this, a request is fast enough that a spinner is noise. */
export const REVEAL_DELAY_MS = 200

/** Once shown, a spinner stays at least this long. */
export const MINIMUM_VISIBLE_MS = 400

export function useSettledSpinner(loading: boolean): boolean {
  const [visible, setVisible] = useState(false)
  const shownAt = useRef<number | null>(null)

  useEffect(() => {
    if (loading) {
      // RULE ONE. Nothing paints until the delay has passed, so a
      // request that finishes first never produces a spinner at all.
      const reveal = setTimeout(() => {
        shownAt.current = Date.now()
        setVisible(true)
      }, REVEAL_DELAY_MS)
      return () => clearTimeout(reveal)
    }

    if (shownAt.current === null) {
      // Never shown, so there is nothing to hold.
      setVisible(false)
      return
    }

    // RULE TWO. It is on screen; keep it there long enough to read as
    // a wait rather than a flicker.
    const elapsed = Date.now() - shownAt.current
    const remaining = MINIMUM_VISIBLE_MS - elapsed
    if (remaining <= 0) {
      shownAt.current = null
      setVisible(false)
      return
    }
    const hold = setTimeout(() => {
      shownAt.current = null
      setVisible(false)
    }, remaining)
    return () => clearTimeout(hold)
  }, [loading])

  return visible
}
