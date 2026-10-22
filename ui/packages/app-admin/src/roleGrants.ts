/**
 * Grants, arranged for a person to read -- and a change, described as
 * what it adds and removes.
 *
 * AN APPROVER READS A DIFFERENCE, NOT TWO LISTS. A role holds dozens of
 * grants; asking somebody to compare a before list with an after list
 * by eye is asking them to miss the one line that matters. So a change
 * is shown as what it ADDS and what it REMOVES, and nothing else.
 */

import type { ModulePermission } from '@elysium/shell-api/api'

export interface GrantGroup {
  title: string
  grants: string[]
  /** What a grant allows, where the registry says (a module's declared
   *  permissions): shown beside the grant, which alone says little. */
  descriptions?: Record<string, string>
}

/** Administration first: those are the grants that change who may do
 *  what, and they should be the first thing an editor sees. Then each
 *  MODULE'S DECLARED PERMISSIONS (BLOCKING.md item 3, step 2.3), a group
 *  per module, described -- and last, any held from a module no longer
 *  listed, so they can be seen and taken away. */
export function groupGrants(
  grantable: string[],
  modulePermissions: ModulePermission[] = [],
  unlisted: string[] = [],
): GrantGroup[] {
  const administration: string[] = []
  const actions: string[] = []
  const tools: string[] = []
  const byType = new Map<string, string[]>()
  const byModule = new Map<string, GrantGroup>()
  const declared = new Map(modulePermissions.map((p) => [p.grant, p]))

  for (const grant of grantable) {
    const [verb, subject = ''] = grant.split(':', 2)
    if (verb === 'module') {
      const permission = declared.get(grant)
      const title = `Module: ${permission?.module_name ?? subject}`
      const group = byModule.get(title) ?? { title, grants: [], descriptions: {} }
      group.grants.push(grant)
      if (permission !== undefined) group.descriptions![grant] = permission.description
      byModule.set(title, group)
    } else if (verb === 'manage' || grant === 'discover:action_types') {
      administration.push(grant)
    } else if (verb === 'execute') {
      actions.push(grant)
    } else if (verb === 'tool') {
      tools.push(grant)
    } else {
      const type = subject.split('.', 1)[0] ?? subject
      byType.set(type, [...(byType.get(type) ?? []), grant])
    }
  }

  const groups: GrantGroup[] = []
  if (administration.length > 0) groups.push({ title: 'Administration', grants: administration })
  if (actions.length > 0) groups.push({ title: 'Actions', grants: actions })
  if (tools.length > 0) groups.push({ title: 'Tools', grants: tools })
  groups.push(...byModule.values())
  for (const [type, grants] of [...byType.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    groups.push({ title: type, grants })
  }
  if (unlisted.length > 0) {
    groups.push({
      title: 'From modules no longer listed',
      grants: unlisted,
      descriptions: Object.fromEntries(
        unlisted.map((grant) => [grant, 'Grants nothing while its module is not listed.']),
      ),
    })
  }
  return groups
}

export interface ChangeSummary {
  kind: 'create' | 'delete' | 'edit'
  added: string[]
  removed: string[]
}

export function summariseChange(before: string[] | null, after: string[] | null): ChangeSummary {
  if (before === null) return { kind: 'create', added: [...(after ?? [])].sort(), removed: [] }
  if (after === null) return { kind: 'delete', added: [], removed: [...before].sort() }
  const was = new Set(before)
  const will = new Set(after)
  return {
    kind: 'edit',
    added: after.filter((grant) => !was.has(grant)).sort(),
    removed: before.filter((grant) => !will.has(grant)).sort(),
  }
}
