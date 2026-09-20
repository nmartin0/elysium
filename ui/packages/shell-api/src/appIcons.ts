/**
 * appIcons.ts -- which icon stands for which sub-app.
 *
 * A FRONTEND concern, keyed by route. The API returns a name and a
 * path; it has no business knowing Blueprint icon names, and putting
 * them in the ontology would make a presentation choice into a
 * deployment one.
 *
 * ICONS ARE CHOSEN FOR WHAT THE APP DOES, not for what it is called.
 * Query is the conversational, natural-language surface, so it takes
 * `chat`; Browse is the one with a search box, so it takes `search`.
 * Naming them the other way round -- which is the intuitive reading of
 * the words alone -- would put a magnifying glass on the app with no
 * search in it.
 *
 * Admin gets `people` rather than `cog`: it manages USERS, and a cog
 * says "preferences" to everyone who has used a computer.
 *
 * Approvals gets `inbox` rather than a tick: the rail says where you
 * are GOING, not what you will do when you arrive, and the page is
 * equally somewhere to reject a write or watch one you proposed.
 *
 * Blueprint's icon set, Apache-2.0 and already a dependency. A second
 * icon library would be a second visual language for no gain.
 */

import type { IconName } from '@blueprintjs/icons'

const BY_PATH: Record<string, IconName> = {
  '/query': 'chat',
  '/browse': 'search',
  '/schema': 'diagram-tree',
  '/admin': 'people',
  // `inbox`, not `endorsed` or `tick`: the rail says where you are
  // going, not what you will do when you arrive. A tick would promise
  // approval and the page is equally a place to reject, or to watch
  // something you proposed.
  '/approvals': 'inbox',
  // A BELL, not an envelope: this is what the deployment told you,
  // not mail somebody sent.
  '/notifications': 'notifications',
}

/**
 * Falls back to a neutral icon rather than nothing.
 *
 * A rail item with no icon collapses to an empty box, and a new
 * sub-app should look unfamiliar rather than broken.
 */
export function iconForApp(path: string): IconName {
  return BY_PATH[path] ?? 'application'
}
