/**
 * EmptyState -- a panel with nothing in it, saying why (DEV_UI 9.7, E2).
 *
 * "EMPTY: icon, title, the REASON it is empty, and an action. 'No
 * objects match these filters' with a clear-filters button, never a
 * blank panel."
 *
 * THE REASON IS REQUIRED, which is the whole of this wrapper. Blueprint's
 * NonIdealState takes a `description` and lets it be left out, and an
 * empty state without one is the "nothing here" that reads as a fault.
 * Five panels used it directly; each said why, by habit. This makes it a
 * rule rather than a habit.
 */

import { NonIdealState } from '@blueprintjs/core'
import type { IconName } from '@blueprintjs/core'
import type { ReactNode } from 'react'

interface EmptyStateProps {
  icon: IconName
  title: string
  /** Why it is empty -- in the reader's terms, not the system's. */
  reason: ReactNode
  /** The way out, when there is one: clear the filters, go and make one. */
  action?: React.JSX.Element
}

export default function EmptyState({ icon, title, reason, action }: EmptyStateProps) {
  return <NonIdealState icon={icon} title={title} description={reason} action={action} />
}
