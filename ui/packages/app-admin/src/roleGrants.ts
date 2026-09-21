/**
 * Grants, arranged for a person to read -- and a change, described as
 * what it adds and removes.
 *
 * AN APPROVER READS A DIFFERENCE, NOT TWO LISTS. A role holds dozens of
 * grants; asking somebody to compare a before list with an after list
 * by eye is asking them to miss the one line that matters. So a change
 * is shown as what it ADDS and what it REMOVES, and nothing else.
 */

export interface GrantGroup {
  title: string
  grants: string[]
}

/** Administration first: those are the grants that change who may do
 *  what, and they should be the first thing an editor sees. */
export function groupGrants(grantable: string[]): GrantGroup[] {
  const administration: string[] = []
  const actions: string[] = []
  const tools: string[] = []
  const byType = new Map<string, string[]>()

  for (const grant of grantable) {
    const [verb, subject = ''] = grant.split(':', 2)
    if (verb === 'manage' || grant === 'discover:action_types') {
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
  for (const [type, grants] of [...byType.entries()].sort(([a], [b]) => a.localeCompare(b))) {
    groups.push({ title: type, grants })
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
