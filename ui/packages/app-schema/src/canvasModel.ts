/**
 * What the ontology canvas draws, from the caller's visible schema.
 *
 * TYPES AS NODES, LINKS AS EDGES, ACTIONS ON THE NODE (DEV_UI 14.3).
 * Event Storming puts commands on its canvas as their own shapes, but
 * that canvas is "about BEHAVIOUR OVER TIME"; an ontology canvas is
 * about STRUCTURE and has no time axis. So an action is a count on the
 * type it affects -- which keeps "which types are writable" visible at
 * a glance -- and is listed in the inspector, not drawn as a node.
 *
 * DERIVED FROM visible_schema, so a type the caller cannot see is not a
 * node they can see; that falls out of the source, not a check here.
 */

import type { VisibleSchema } from '@elysium/shell-api/types'

import { groupLinkTypes } from './LinkTypes'

/**
 * A cardinality as it is written on an ER diagram: one_to_many is 1:M,
 * because an edge label competes with the node labels around it and the
 * short form is the one people already read. M:M is written M:N -- two
 * "many" sides are not the same many.
 */
export function cardinalityLabel(cardinality: string): string {
  const parts = cardinality.split('_to_')
  if (parts.length !== 2) return cardinality
  const symbol = (side?: string) => (side === 'many' ? 'M' : '1')
  const left = symbol(parts[0])
  const right = symbol(parts[1])
  if (left === 'M' && right === 'M') return 'M:N'
  return `${left}:${right}`
}

export interface CanvasType {
  name: string
  label: string
  /** Data fields, not links -- the links are the edges. */
  fieldCount: number
  /** Their display names, the KEY first and the rest in declaration
   *  order: what the node lists at close zoom (DEV_UI 14.5). */
  fields: string[]
  /** The display name of the field that identifies an object, or null. */
  key: string | null
  linkCount: number
  /** Actions that affect this type, by api name, sorted. */
  actions: string[]
  /** The author's grouping from the ontology, if any (a ready-made
   *  subject area, 14.4). */
  group: string | null
  /** The caller may know this type exists and not open it: its name is
   *  listed to them (by a discover grant, or because its owner listed it
   *  to everyone) and `readable` is false. Drawn as view-only. */
  locked: boolean
}

interface CanvasLink {
  /** The link type's name; two different link types between one pair
   *  are two edges. */
  name: string
  source: string
  target: string
  label: string
}

export interface CanvasModel {
  types: CanvasType[]
  links: CanvasLink[]
}

interface ActionSummary {
  affected_object_types?: string[]
}

export function buildCanvasModel(schema: VisibleSchema, actionTypes: Record<string, ActionSummary> = {}): CanvasModel {
  const names = Object.keys(schema).sort((a, b) => a.localeCompare(b))
  const known = new Set(names)

  // An action touching only types this caller cannot see counts nowhere:
  // a badge for it would say "there is something here you may not see".
  const actionsByType = new Map<string, string[]>()
  for (const [apiName, action] of Object.entries(actionTypes)) {
    for (const type of action.affected_object_types ?? []) {
      if (!known.has(type)) continue
      actionsByType.set(type, [...(actionsByType.get(type) ?? []), apiName])
    }
  }

  const types = names.map((name) => {
    const fields = Object.values(schema[name]?.fields ?? {})
    const entries = Object.entries(schema[name]?.fields ?? {}).filter(([, field]) => field.type !== 'link')
    const keyName = schema[name]?.id_field ?? null
    const keyEntry = entries.find(([apiName]) => apiName === keyName)
    const shown = (apiName: string, display?: string | null) => display ?? apiName
    return {
      name,
      label: schema[name]?.display_name ?? name,
      fieldCount: fields.filter((field) => field.type !== 'link').length,
      // THE KEY NEED NOT BE A DECLARED FIELD -- the fixture's Customer
      // names id_field customer_id and declares no such field -- so it is
      // listed by its own name then, rather than dropped.
      fields: [
        ...(keyEntry ? [shown(keyEntry[0], keyEntry[1].display_name)] : keyName ? [keyName] : []),
        ...entries
          .filter(([apiName]) => apiName !== keyName)
          .map(([apiName, field]) => shown(apiName, field.display_name)),
      ],
      key: keyEntry ? shown(keyEntry[0], keyEntry[1].display_name) : keyName,
      linkCount: fields.filter((field) => field.type === 'link').length,
      actions: [...(actionsByType.get(name) ?? [])].sort((a, b) => a.localeCompare(b)),
      group: schema[name]?.group ?? null,
      locked: schema[name]?.readable === false,
    }
  })

  const links: CanvasLink[] = []
  const seen = new Set<string>()
  for (const [linkType, sides] of groupLinkTypes(schema)) {
    for (const side of sides) {
      // An edge to a type that is not drawn is a drawing bug, not a
      // security decision -- the schema is already scoped.
      if (!known.has(side.target) || !known.has(side.objectType)) continue
      // BOTH SIDES OF A LINK TYPE ARE ONE RELATIONSHIP, drawn once.
      const pair = [side.objectType, side.target].sort().join('\u0000') + linkType
      if (seen.has(pair)) continue
      seen.add(pair)
      links.push({
        name: linkType,
        source: side.objectType,
        target: side.target,
        label: cardinalityLabel(side.cardinality),
      })
    }
  }
  links.sort((a, b) => `${a.source}>${a.target}>${a.name}`.localeCompare(`${b.source}>${b.target}>${b.name}`))
  return { types, links }
}

export interface SubjectArea {
  name: string
  types: string[]
  /** From the ontology's own `group`, which this person cannot edit. */
  declared: boolean
}

/** The author's groups, as subject areas offered before anyone makes one. */
export function declaredAreas(types: CanvasType[]): SubjectArea[] {
  const groups = new Map<string, string[]>()
  for (const type of types) {
    if (!type.group) continue
    groups.set(type.group, [...(groups.get(type.group) ?? []), type.name])
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([name, members]) => ({ name, types: members, declared: true }))
}
