/**
 * ErrorState -- something failed, said out loud.
 *
 * THE TREATMENT WAS ALREADY CONSISTENT. Ten components render
 * `<Callout intent="danger">` and nine are byte-identical, so unlike
 * the loading states there was nothing to reconcile. This exists for
 * the thing none of them did.
 *
 * A DANGER CALLOUT ANNOUNCES NOTHING. Blueprint sets no ARIA role on
 * it -- verified against the built package, not assumed -- so an error
 * appearing after an action is invisible to a screen reader. Someone
 * submits a write, it is rejected, and they hear silence: the same
 * silence as success. That is worse than a missing label on a spinner,
 * because a spinner eventually resolves and a failure just sits there.
 *
 * role="alert" rather than "status": an alert is announced
 * IMMEDIATELY, interrupting whatever else was being read. Errors earn
 * that and progress does not, which is why LoadingState uses "status"
 * and this does not.
 *
 * THE BACKEND'S WORDING IS PRESERVED. The API returns real messages
 * for caller mistakes -- an unknown aggregate names the valid ones --
 * and this renders whatever it is given rather than substituting a
 * house phrase. The person who most needs the detail is the one who
 * just made the mistake.
 */

import { Callout } from '@blueprintjs/core'
import type { ReactNode } from 'react'

interface ErrorStateProps {
  /** What went wrong, in the words it arrived in. */
  children: ReactNode
  /** A heading, for a summary of several failures rather than one.
   *  Silos uses it; a single message should not. */
  title?: string
}

export default function ErrorState({ children, title }: ErrorStateProps) {
  return (
    <Callout intent="danger" title={title} role="alert">
      {children}
    </Callout>
  )
}
