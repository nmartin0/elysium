/**
 * StatusTag -- a tag, which in this application always means a state.
 *
 * THE NUMBERS MADE THIS ONE OBVIOUS. `<Tag>` appears 43 times and
 * FORTY of those pass `minimal` -- 93%. Three do not, and reading them
 * showed no reason beyond somebody forgetting. That is not a prop, it
 * is a default that was never written down.
 *
 * THE INTENTS ARE NOT DECORATION. Across the screens a tag means one
 * of four things, and the Blueprint intent is how it says so:
 *
 *   warning   pending, awaiting someone, not yet settled   (10 uses)
 *   primary   a live or current value                      ( 7 uses)
 *   success   granted, approved, published                 ( 2 uses)
 *   danger    refused, revoked, failed                     ( 2 uses)
 *
 * Naming them removes the question "is a rejected write danger or
 * warning?" from every future screen -- which is the kind of question
 * that gets answered differently each time and then looks arbitrary to
 * the person reading the app.
 *
 * NO `minimal` ESCAPE. The three non-minimal uses are being brought
 * into line rather than preserved. If a loud tag is ever genuinely
 * needed, import Blueprint's Tag directly and say why; an option here
 * would just recreate the drift.
 */

import { Tag } from '@blueprintjs/core'
import type { TagProps } from '@blueprintjs/core'

export type TagState =
  /** Neutral. A label, a count, a name. */
  | 'neutral'
  /** Waiting on a person or a process. */
  | 'pending'
  /** Live, current, selected. */
  | 'active'
  /** Granted, approved, published. */
  | 'granted'
  /** Refused, revoked, failed. */
  | 'refused'

const INTENT = {
  neutral: undefined,
  pending: 'warning',
  active: 'primary',
  granted: 'success',
  refused: 'danger',
} as const

interface StatusTagProps extends Omit<TagProps, 'intent' | 'minimal'> {
  state?: TagState
}

export default function StatusTag({ state = 'neutral', ...rest }: StatusTagProps) {
  return <Tag minimal intent={INTENT[state]} {...rest} />
}
