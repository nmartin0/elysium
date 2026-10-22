/** WHAT THE IDENTITY MODULE PUTS IN OTHER MODULES' SLOTS (step 1.5b): the
 *  Inbox's Identity tab, loaded when it is first opened. Its icon
 *  (module.json) is merge-columns: the tab is about deciding whether two
 *  records are ONE. A padlock would say "security" and mislead. */
import { lazy } from 'react'

export const contributions = {
  identity: lazy(() => import('./IdentityPanel')),
}
