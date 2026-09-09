/**
 * What a node or edge in the ontology graph actually is.
 *
 * WITHOUT LEAVING THE GRAPH, which is the point. Clicking used to
 * navigate to Object types, and coming back re-laid the graph out --
 * so exploring cost you your place every time. That is the difference
 * between a diagram and a tool, and it is the gap Foundry's own
 * version closes with "a quick view of an object type without moving
 * into the more comprehensive exploration page".
 *
 * There is still a way out: the panel offers to open the full view for
 * when someone wants it, rather than deciding for them that they do.
 */

import { Button, Tag } from '@blueprintjs/core'

import type { VisibleSchema } from '@elysium/shell-api/types'
import { formatFieldName } from '@elysium/shell-api/format'

import { groupLinkTypes } from './LinkTypes'

export type GraphSelection =
  | { kind: 'object'; name: string }
  | { kind: 'action'; name: string }
  | { kind: 'link'; name: string; source: string; target: string; label: string }

interface GraphPreviewProps {
  selection: GraphSelection
  schema: VisibleSchema
  actionTypes: Record<string, {
    display_name?: string | null
    description?: string | null
    affected_object_types?: string[]
    parameters?: Record<string, {
      type?: string
      object_type?: string
      required?: boolean
      display_name?: string | null
    }>
  }>
  onOpenFull: (name: string, kind: 'object' | 'action' | 'link') => void
}

export default function GraphPreview({
  selection, schema, actionTypes, onOpenFull,
}: GraphPreviewProps) {
  if (selection.kind === 'link') {
    // BOTH SIDES. A link type is one relationship declared as two
    // fields on two types, and naming only the endpoints leaves out
    // the thing you would actually write in a query -- which field on
    // which type gets you across.
    const sides = groupLinkTypes(schema).get(selection.name) ?? []

    return (
      <div className="graph-preview">
        <p className="graph-preview__kind">Link type</p>
        <h3>{selection.name}</h3>
        <p className="graph-preview__joins">
          {selection.source} <Tag minimal>{selection.label}</Tag> {selection.target}
        </p>

        <h4>Fields</h4>
        <ul className="graph-preview__fields">
          {sides.map((side) => (
            <li key={`${side.objectType}.${side.apiName}`}>
              {side.objectType}.{side.apiName}
              <span className="graph-preview__type"> {side.cardinality} {side.target}</span>
            </li>
          ))}
        </ul>

        {/* Missing entirely before: a link was the one thing you could
            select and not open. */}
        <Button minimal small onClick={() => onOpenFull(selection.name, 'link')}>
          Open in Link types
        </Button>
      </div>
    )
  }

  if (selection.kind === 'action') {
    const action = actionTypes[selection.name]
    return (
      <div className="graph-preview">
        <p className="graph-preview__kind">Action type</p>
        <h3>{action?.display_name ?? selection.name}</h3>
        {action?.description && <p>{action.description}</p>}
        <p className="graph-preview__affects">
          Affects: {(action?.affected_object_types ?? []).join(', ') || '—'}
        </p>

        {/* PARAMETERS are an action's equivalent of fields, and the
            preview showed none -- so selecting an action told you less
            than selecting anything else. */}
        <h4>Parameters</h4>
        <ul className="graph-preview__fields">
          {Object.entries(action?.parameters ?? {}).map(([name, parameter]) => (
            <li key={name}>
              {formatFieldName(parameter.display_name ?? name)}
              <span className="graph-preview__type">
                {' '}{parameter.object_type ?? parameter.type}
              </span>
              {parameter.required && (
                <Tag minimal intent="primary" className="graph-preview__visibility">required</Tag>
              )}
            </li>
          ))}
        </ul>
        <Button minimal small onClick={() => onOpenFull(selection.name, 'action')}>
          Open in Action types
        </Button>
      </div>
    )
  }

  const type = schema[selection.name]
  const fields = Object.entries(type?.fields ?? {})
  // Links listed apart from data fields: they are the graph's own
  // edges, and seeing them beside the picture is what makes the
  // picture legible.
  const dataFields = fields.filter(([, f]) => f.type !== 'link')
  const linkFields = fields.filter(([, f]) => f.type === 'link')

  return (
    <div className="graph-preview">
      <p className="graph-preview__kind">Object type</p>
      <h3>{type?.display_name ?? selection.name}</h3>
      {type?.description && <p>{type.description}</p>}

      <h4>Fields</h4>
      <ul className="graph-preview__fields">
        {dataFields.map(([name, field]) => (
          <li key={name}>
            {formatFieldName(field.display_name ?? name)}
            {field.data_type && <span className="graph-preview__type"> {field.data_type}</span>}
            {/* Visibility, when the author declared it. A hidden field
                shown as equal to a prominent one overstates it. The
                fixture ontology declares none, so this path is
                exercised by tests rather than by the dev deployment. */}
            {field.visibility && field.visibility !== 'normal' && (
              <Tag minimal className="graph-preview__visibility">{field.visibility}</Tag>
            )}
          </li>
        ))}
      </ul>

      {linkFields.length > 0 && (
        <>
          <h4>Links</h4>
          <ul className="graph-preview__fields">
            {linkFields.map(([name, field]) => (
              <li key={name}>
                {formatFieldName(name)} <span className="graph-preview__type">
                  {field.target}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}

      <Button minimal small onClick={() => onOpenFull(selection.name, 'object')}>
        Open in Object types
      </Button>
    </div>
  )
}
