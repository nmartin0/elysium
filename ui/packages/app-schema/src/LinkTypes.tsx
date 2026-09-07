/**
 * Link types, reconstructed from the object types.
 *
 * The API returns object types with their link FIELDS expanded, not a
 * list of link types -- so both directions of one relationship arrive
 * as two separate fields on two different object types, joined only by
 * a shared `link_type` name. This groups them back.
 *
 * Done client-side because no API change is needed: every generated
 * link field already carries its link_type. Verified against the
 * fixture, where four relationships each produce exactly two sides.
 *
 * A side may be MISSING. If the caller can read one end of a
 * relationship and not the other, only one side arrives -- which is
 * uniform denial working, not data loss, and is shown as a
 * relationship with one known end rather than hidden entirely.
 */

import { Button, HTMLTable, Tag } from '@blueprintjs/core'
import type { VisibleSchema } from '@elysium/shell-api/types'

// Not exported: used only within this file. Exporting a type nothing
// imports is a second, unused public surface to keep correct.
interface LinkSide {
  objectType: string
  apiName: string
  target: string
  cardinality: string
}

export function groupLinkTypes(schema: VisibleSchema): Map<string, LinkSide[]> {
  const grouped = new Map<string, LinkSide[]>()
  for (const [objectType, type] of Object.entries(schema)) {
    for (const [apiName, field] of Object.entries(type.fields ?? {})) {
      if (field.type !== 'link' || !field.link_type) continue
      const sides = grouped.get(field.link_type) ?? []
      sides.push({
        objectType,
        apiName,
        target: field.target ?? '?',
        cardinality: field.cardinality ?? 'one',
      })
      grouped.set(field.link_type, sides)
    }
  }
  return grouped
}

interface LinkTypesProps {
  schema: VisibleSchema
  filter: string
  /** Opens an object type -- one end of a relationship is a thing you
   *  usually want to look at next. */
  onOpenObjectType: (objectType: string) => void
}

export default function LinkTypes({ schema, filter, onOpenObjectType }: LinkTypesProps) {
  const grouped = groupLinkTypes(schema)
  if (grouped.size === 0) {
    return <p>No link types are visible to you.</p>
  }

  const needle = filter.trim().toLowerCase()
  const matches = [...grouped.entries()]
    .filter(([linkType, sides]) =>
      needle === ''
      || linkType.toLowerCase().includes(needle)
      || sides.some((side) => side.objectType.toLowerCase().includes(needle)
        || side.target.toLowerCase().includes(needle)))
    .sort(([a], [b]) => a.localeCompare(b))

  if (matches.length === 0) {
    return <p>No link type matches {filter}.</p>
  }

  return (
    <HTMLTable compact striped className="schema-panel__fields">
      <thead>
        <tr>
          <th>Link type</th>
          <th>From</th>
          <th>To</th>
        </tr>
      </thead>
      <tbody>
        {matches.map(([linkType, sides]) => (
            <tr key={linkType}>
              <td>
                <strong>{linkType}</strong>
                {sides.length === 1 && (
                  <div className="schema-panel__api-name">one side visible to you</div>
                )}
              </td>
              {sides.slice(0, 2).map((side) => (
                <td key={`${side.objectType}.${side.apiName}`}>
                  <Button minimal small onClick={() => onOpenObjectType(side.objectType)}>
                    {side.objectType}
                  </Button>
                  <div className="schema-panel__api-name">
                    {side.apiName} &rarr; <Tag minimal>{side.cardinality}</Tag> {side.target}
                  </div>
                </td>
              ))}
              {sides.length === 1 && <td />}
            </tr>
        ))}
      </tbody>
    </HTMLTable>
  )
}
