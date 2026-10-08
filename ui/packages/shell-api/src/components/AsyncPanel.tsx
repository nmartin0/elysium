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

import { useSettledSpinner } from '../useSettledSpinner'
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
   * THE SPINNER IS DELAYED, AND HELD ONCE SHOWN. It used to mount the
   * instant `data` was null, so a request answering in 90ms produced a
   * few frames of grey and vanished -- read as the screen flinching
   * rather than as loading. See useSettledSpinner for both rules and
   * why one of them is not enough.
   *
   * NOTHING ELSE RENDERS IN ITS PLACE while the delay runs. An empty
   * region for 200ms is what a fast response should look like; filling
   * it with a placeholder would reintroduce exactly the flicker this
   * removes.
   */
  const waiting = data === null || data === undefined
  const showSpinner = useSettledSpinner(waiting)

  if (error !== null) return <Callout intent="danger">{error}</Callout>
  if (waiting) return showSpinner ? <Spinner /> : null
  return <>{children(data)}</>
}
