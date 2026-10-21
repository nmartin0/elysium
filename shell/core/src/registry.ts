/**
 * What the shell builds from a feed: the rail, the pages to mount, and
 * the old addresses that still lead somewhere.
 *
 * PURE, so the shell's whole picture of its modules can be tested without
 * a page, and recomputed when the feed changes.
 *
 * A PATH BELONGS TO ONE MODULE. Two modules claiming the same page path
 * would otherwise race, and which one a person reached would depend on
 * feed order -- an accident nobody chose. The first keeps it and the
 * clash is reported, so the module manager can say which module lost and
 * why.
 *
 * ONE SUBJECT, ONE RUN OF THE RAIL. Entries keep feed order, except that
 * every entry of a subject follows the first one: a rail heading per
 * subject is drawn where the subject changes, and a feed listing
 * Objects, Settings, Objects would otherwise draw Objects twice.
 */
import type { ModuleFeed, NavContribution } from './contract'

export interface MountedPage {
  moduleId: string
  pageId: string
  path: string
}

export interface NavItem extends NavContribution {
  moduleId: string
}

export interface Registry {
  pages: MountedPage[]
  nav: NavItem[]
  redirects: { from: string; to: string }[]
  /** What could not be honoured, each a sentence naming the module. */
  problems: string[]
}

export function buildRegistry(feed: ModuleFeed): Registry {
  const pages: MountedPage[] = []
  const nav: NavItem[] = []
  const redirects: { from: string; to: string }[] = []
  const problems: string[] = []
  const owner = new Map<string, string>()

  for (const module of feed.modules) {
    const own = new Set<string>()
    for (const page of module.contributes.pages ?? []) {
      const holder = owner.get(page.path)
      if (holder !== undefined) {
        problems.push(`${module.id}: the page ${page.path} is already ${holder}'s, so it is not mounted`)
        continue
      }
      owner.set(page.path, module.id)
      own.add(page.path)
      pages.push({ moduleId: module.id, pageId: page.id, path: page.path })
    }
    for (const entry of module.contributes.nav ?? []) {
      // A RAIL ENTRY LEADS TO THE MODULE'S OWN PAGE. One pointing
      // elsewhere would be a link the module does not own and cannot
      // keep working.
      if (!own.has(entry.path)) {
        problems.push(
          `${module.id}: its rail entry ${entry.title} leads to ${entry.path}, which is not one of its pages`,
        )
        continue
      }
      nav.push({ ...entry, moduleId: module.id })
    }
    for (const redirect of module.contributes.redirects ?? []) {
      const holder = owner.get(redirect.from)
      if (holder !== undefined) {
        problems.push(`${module.id}: ${redirect.from} is ${holder}'s page, so it is not redirected`)
        continue
      }
      owner.set(redirect.from, module.id)
      redirects.push(redirect)
    }
  }
  return { pages, nav: groupedBySubject(nav), redirects, problems }
}

function groupedBySubject(nav: NavItem[]): NavItem[] {
  const order: (string | undefined)[] = []
  for (const entry of nav) if (!order.includes(entry.subject)) order.push(entry.subject)
  return order.flatMap((subject) => nav.filter((entry) => entry.subject === subject))
}
