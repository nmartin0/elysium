/**
 * AsyncPanel -- show the failure, or the wait, or the content.
 *
 * Four screens wrote the same two lines: an early return with a danger
 * Callout, then an early return with a Spinner. Identical apart from
 * which state variable they checked.
 *
 * EARLY RETURN, NOT AN INLINE BANNER, and that distinction is why this
 * is one component rather than two. A screen with nothing to show
 * REPLACES itself with the failure; a screen that still has content
 * shows a banner ABOVE it and keeps working. Browse does the second --
 * a failed refetch leaves the previous results readable, which is
 * better than blanking them - so it is deliberately not a caller here.
 *
 * Conflating the two would mean an option deciding which, and a
 * component whose options change what it fundamentally is has stopped
 * being one component.
 *
 * NOT AN ERROR BOUNDARY. It renders an error someone already caught
 * and put in state. A thrown render error blanks the page and needs
 * different machinery -- see the graph's white screen for what that
 * looks like.
 */

import type { ReactNode } from 'react'
import { Callout, Spinner } from '@blueprintjs/core'

interface AsyncPanelProps<T> {
  /** A message, or null. Takes precedence over loading: a request that
   *  failed is not still in flight, and showing a spinner over a known
   *  failure waits for something that will never arrive. */
  error: string | null
  /** Null means "not here yet". Deliberately the DATA rather than a
   *  boolean, so a caller cannot render content and a spinner at once
   *  by getting two flags out of step. */
  data: T | null | undefined
  /**
   * A FUNCTION, not a node, and that is not ceremony.
   *
   * The early returns this replaces narrowed the type: after
   * `if (config === null) return`, TypeScript knew config was not
   * null for the rest of the function. A wrapper component cannot do
   * that -- the children are constructed before it decides anything --
   * so a plain-node version forced every caller into `config!` or an
   * optional chain on a value that is definitely present.
   *
   * Passing the narrowed value back is what preserves the guarantee
   * the early return gave for free.
   */
  children: (data: T) => ReactNode
}

export default function AsyncPanel<T>({ error, data, children }: AsyncPanelProps<T>) {
  /**
   * THE SPINNER FADES IN AFTER A DELAY, IN CSS, WITH NO TIMER HERE.
   *
   * It used to mount the instant `data` was null, so a request
   * answering in 90ms produced a few frames of grey and vanished --
   * read as the screen flinching rather than as loading. Elysium's
   * reads come from a local mirror, so the fast case is the common one.
   *
   * A FIRST ATTEMPT DID THIS IN JAVASCRIPT and it was wrong. A hook
   * holding `setTimeout` for a reveal delay and a minimum visible time
   * lands a state update after a test has stopped watching, which
   * setupTests.ts turns into a thrown act() warning -- three of them,
   * in a race-condition test that deliberately leaves promises
   * unresolved across `waitFor`. Pushing timer-flushing into every
   * panel test to pay for a spinner is the wrong trade.
   *
   * `.spinner-delayed` carries the whole behaviour: opacity 0, a
   * fade-in that starts at 200ms and runs for 600. A spinner that
   * unmounts before 200ms was never visible, and one that unmounts
   * shortly after is still almost transparent -- which is the second
   * rule the sources give, that a spinner appearing for 30ms is "a
   * two-frame flash, which is worse", handled by never reaching full
   * opacity rather than by holding it on screen.
   */
  if (error !== null) return <Callout intent="danger">{error}</Callout>
  if (data === null || data === undefined) {
    return (
      <div className="spinner-delayed">
        <Spinner />
      </div>
    )
  }
  return <>{children(data)}</>
}
