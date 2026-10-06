/**
 * Notice -- a callout, which in this application always says something
 * about the state of what you are looking at.
 *
 * THE NUMBERS. `<Callout>` appears 18 times. ELEVEN are neutral, and
 * eight of those type `intent="none"` explicitly -- a prop whose only
 * effect is to restate the default. The remaining seven split three
 * warning, three primary, two success.
 *
 * ONE VOCABULARY ACROSS THE KIT. The states are the same words
 * StatusTag uses -- pending, active, granted, refused -- rather than
 * Blueprint's intents. A developer learns the vocabulary once and it
 * means the same thing on a tag and on a callout, which is the actual
 * benefit of a kit: "the gained consistency of reducing the used API
 * surface of the external library".
 *
 * DANGER IS NOT HERE. `ErrorState` already owns it, and for a reason
 * worth keeping separate: a danger callout gets `role="alert"` so a
 * screen reader interrupts with it. A notice is not an error and must
 * not announce like one. Routing both through one component would lose
 * that distinction the first time somebody passed state="refused" to
 * report something merely unavailable.
 */

import { Callout } from '@blueprintjs/core'
import type { CalloutProps } from '@blueprintjs/core'

export type NoticeState =
  /** The default, and what eleven of eighteen existing callouts are. */
  | 'neutral'
  /** Waiting on a person or a process. */
  | 'pending'
  /** Live, current, worth noticing. */
  | 'active'
  /** Succeeded, published, approved. */
  | 'granted'

const INTENT = {
  neutral: 'none',
  pending: 'warning',
  active: 'primary',
  granted: 'success',
} as const

interface NoticeProps extends Omit<CalloutProps, 'intent'> {
  state?: NoticeState
}

export default function Notice({ state = 'neutral', ...rest }: NoticeProps) {
  return <Callout intent={INTENT[state]} {...rest} />
}
